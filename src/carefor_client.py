"""
케어포 로그인 + 데이터 수집 (Playwright headless).

전략:
1. 자동로그인 portal HTML에서 지점별 자격증명 자동 추출
2. login2(ctmnumb) 호출 → 새 탭으로 SPA 진입
3. 새 탭에서 g_pammgno (지점별 관리번호) 추출
4. SPA hash URL 직접 구성하여 데이터 화면으로 이동
5. DOM에서 텍스트 추출

SPA URL 형식 (hash routing, base64):
  https://dn.carefor.co.kr/#<base64>
  decode: page|{type, view}%{title, g_pammgno, move_scroll}|<type>

데이터 화면:
  - 수급자 현황(1-7): type=left_sub1, view=/share/patient/view.patient_report
  - 시설운영일지(6-4): type=left_sub6, view=/safe/view.daily_center
  - 월간 입소자(2-8): type=left_sub2, view=/transport/view.monthly_attend_stat
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import date

from playwright.sync_api import Page, sync_playwright

from . import credentials


@dataclass
class BranchAttendance:
    name: str
    ctmnumb: str
    hyeon_won: int      # 현원(수급중)
    gyeol_seok: int     # 결석
    chul_seok: int      # 출석
    avg_attendees: float = 0.0  # 월평균 입소자 수(현월, 진행 중이라 러닝 평균)
    prev_avg_attendees: float | None = None  # 전월 최종 평균 입소자 수(마감값)


PORTAL_URL = "https://eform.caring.co.kr/carefor"
DN_BASE = "https://dn.carefor.co.kr/"


def build_spa_hash(type_: str, view: str, title: str, g_pammgno: str) -> str:
    """SPA hash URL 생성. 사용자 캡쳐한 URL과 동일한 직렬화 포맷 유지."""
    # 두 번째 JSON 객체는 공백 없는 표준 JSON
    json_part = json.dumps(
        {"title": title, "g_pammgno": g_pammgno, "move_scroll": True},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    payload = f"page|{{'type':'{type_}', 'view':'{view}'}}%{json_part}|{type_}"
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def patient_report_url(g_pammgno: str) -> str:
    h = build_spa_hash("left_sub1", "/share/patient/view.patient_report", "1-7.수급자 현황 리포트", g_pammgno)
    return f"{DN_BASE}#{h}"


def daily_center_url(g_pammgno: str) -> str:
    h = build_spa_hash("left_sub6", "/safe/view.daily_center", "6-4.시설운영일지", g_pammgno)
    return f"{DN_BASE}#{h}"


def monthly_attend_url(g_pammgno: str) -> str:
    h = build_spa_hash("left_sub2", "/transport/view.monthly_attend_stat", "2-8.월간 입소자, 일정, 서비스 현황", g_pammgno)
    return f"{DN_BASE}#{h}"


def car_manage_url(g_pammgno: str) -> str:
    h = build_spa_hash("left_sub2", "/transport/view.transport_car_manage", "2-4.차량관리", g_pammgno)
    return f"{DN_BASE}#{h}"


def _navigate_spa(page: Page, full_url: str) -> None:
    """
    SPA hash 변경. hash-only 변경은 reload를 안 일으키므로
    명시적으로 hashchange 이벤트 트리거.
    """
    new_hash = full_url.split("#", 1)[1]
    page.evaluate(
        f"""
        (() => {{
            const newHash = '{new_hash}';
            if (window.location.hash !== '#' + newHash) {{
                window.location.hash = newHash;
            }} else {{
                window.dispatchEvent(new HashChangeEvent('hashchange'));
            }}
        }})()
        """
    )
    # SPA가 새 뷰 렌더링할 시간
    page.wait_for_timeout(1500)


def extract_g_pammgno(page: Page) -> str:
    """
    로그인 직후 페이지에서 g_pammgno 추출.
    SPA가 글로벌 변수나 hash URL에 보유.
    """
    # 1) 현재 URL hash에서 찾기
    url = page.url
    if "#" in url:
        try:
            hash_part = url.split("#", 1)[1]
            decoded = base64.b64decode(hash_part).decode("utf-8")
            m = re.search(r'"g_pammgno":\s*"(\d+)"', decoded)
            if m:
                return m.group(1)
        except Exception:
            pass

    # 2) 페이지의 글로벌 JS 변수에서 찾기
    try:
        result = page.evaluate("typeof g_pammgno !== 'undefined' ? String(g_pammgno) : (window.g_pammgno || '')")
        if result:
            return str(result)
    except Exception:
        pass

    # 3) 페이지 내 input/data 속성에서 찾기
    try:
        result = page.evaluate("""
            (() => {
                const el = document.querySelector('[name="g_pammgno"], [data-pammgno], #g_pammgno');
                return el ? (el.value || el.dataset.pammgno || el.textContent || '') : '';
            })()
        """)
        if result:
            return str(result).strip()
    except Exception:
        pass

    raise RuntimeError("g_pammgno 추출 실패 — 로그인 후 페이지에 해당 값이 없습니다")


def scrape_patient_report(page: Page) -> int:
    """
    1-7 수급자 현황 리포트에서 '수급중' 상태 인원 카운트.
    테이블 셀에서 정확히 '수급중'인 항목만 집계.
    """
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(2000)
    _close_popups(page)
    page.wait_for_timeout(500)

    # 방법 1: 테이블 셀 중 정확히 '수급중'인 것 카운트
    count = page.evaluate("""
        (() => {
            const cells = document.querySelectorAll('td, th');
            let cnt = 0;
            cells.forEach(td => {
                if (td.textContent.trim() === '수급중') cnt++;
            });
            return cnt;
        })()
    """)
    if count > 0:
        return count

    # 방법 2: innerText 줄 단위에서 정확히 '수급중'인 행 카운트
    body_text = page.evaluate("document.body.innerText")
    lines = [l.strip() for l in body_text.split("\n")]
    count = sum(1 for l in lines if l == "수급중")
    if count > 0:
        return count

    raise RuntimeError("1-7 수급자 현황에서 '수급중' 인원을 찾을 수 없습니다")


def scrape_daily_center(page: Page) -> tuple[int, int]:
    """
    시설운영일지 화면에서 현원, 일정 추출.
    출석 = 일정, 결석 = 현원 - 일정
    화면 텍스트 예시:
      "수급자현황(총 73명)"
      "일정(65명)"
    반환: (현원, 일정)
    """
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(2000)
    _close_popups(page)
    page.wait_for_timeout(500)

    body_text = page.evaluate("document.body.innerText")
    print(f"  [DEBUG 6-4] {body_text[:300]}")

    m_hyeon = re.search(r"수급자현황\s*\(\s*총?\s*(\d+)\s*명\s*\)", body_text)
    m_iljung = re.search(r"일정\s*\(\s*(\d+)\s*명\s*\)", body_text)

    if not m_hyeon:
        raise RuntimeError("시설운영일지에서 '수급자현황(총 N명)' 텍스트를 찾을 수 없습니다")
    if not m_iljung:
        raise RuntimeError("시설운영일지에서 '일정(N명)' 텍스트를 찾을 수 없습니다")

    return int(m_hyeon.group(1)), int(m_iljung.group(1))


def _close_popups(page: Page) -> None:
    """팝업/알림창 닫기. 페이지 진입 시 자주 뜸 (수급자 인정 만료 등)."""
    page.wait_for_timeout(500)
    try:
        # "창닫기" 버튼들 모두 클릭
        page.evaluate("""
            (() => {
                const buttons = document.querySelectorAll('button, input[type="button"]');
                let closed = 0;
                buttons.forEach(b => {
                    const txt = (b.textContent || b.value || '').trim();
                    if (['창닫기', '닫기', '확인', 'X', '×'].includes(txt)) {
                        try {
                            const rect = b.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                b.click();
                                closed++;
                            }
                        } catch (e) {}
                    }
                });
                return closed;
            })()
        """)
    except Exception:
        pass


def scrape_monthly_attend(page: Page, target: date) -> tuple[int, float]:
    """
    월간 입소자 화면에서 오늘 날짜 행의 합계 + 월평균 입소자 수 추출.
    반환: (오늘_출석, 월평균)  예) (62, 60.3)
    """
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(2000)
    _close_popups(page)
    page.wait_for_timeout(500)

    date_pattern = target.strftime("%Y.%m.%d")
    date_re = re.compile(r"20\d{2}\.\d{2}\.\d{2}")

    today_total: int | None = None
    daily_totals: list[int] = []

    # 방법 1: <tr><td> 표 구조
    rows = page.evaluate("""
        Array.from(document.querySelectorAll('tr')).map(tr =>
            Array.from(tr.querySelectorAll('td,th')).map(td => td.textContent.trim())
        ).filter(r => r.length > 0)
    """)
    for row in rows:
        has_date = any(date_re.search(cell) for cell in row)
        if not has_date:
            continue
        for cell in reversed(row):
            if re.fullmatch(r"\d+", cell.strip()):
                val = int(cell.strip())
                daily_totals.append(val)
                if any(date_pattern in c for c in row):
                    today_total = val
                break

    if today_total is not None and daily_totals:
        avg = round(sum(daily_totals) / len(daily_totals), 1)
        return today_total, avg

    # 방법 2: 텍스트 라인 매칭
    body_text = page.evaluate("document.body.innerText")
    lines = [l.strip() for l in body_text.split("\n") if l.strip()]
    daily_totals = []

    for i, line in enumerate(lines):
        if not date_re.search(line):
            continue
        nums_in_line = re.findall(r"\b\d+\b", line)
        if len(nums_in_line) >= 6:
            val = int(nums_in_line[-1])
            daily_totals.append(val)
            if date_pattern in line:
                today_total = val
        else:
            following = []
            for j in range(i + 1, min(i + 15, len(lines))):
                if date_re.search(lines[j]):
                    break
                if re.fullmatch(r"-|\d+", lines[j]):
                    following.append(lines[j])
                if len(following) >= 7:
                    break
            if len(following) >= 6:
                last = following[-1]
                if last != "-":
                    val = int(last)
                    daily_totals.append(val)
                    if date_pattern in line:
                        today_total = val

    if today_total is None:
        raise RuntimeError(f"월간 입소자 표에서 {date_pattern} 행을 찾을 수 없습니다")

    # 월평균은 화면이 계산해 둔 값(param-info)을 그대로 쓴다 — 우리가 다시 더하지 않는다.
    # ★일별 합을 평균 내는 폴백은 **틀린 값이 나온다**(실측 2026-07-29 둔산: 107.38, 정답 57.52).
    #   화면에 월별 통계표가 같이 있어 그 숫자까지 섞여 들어가기 때문. 그래서 폴백은 쓰지 않고
    #   0.0(=모름)으로 두어 잘못된 수치가 보고에 실리지 않게 한다.
    avg = 0.0
    try:
        v = _read_avg_param_info(page)
        if v:
            avg = v
        else:
            print("  [WARN] 평균 입소자 param-info 를 못 읽었습니다 — 월평균 미표기로 넘어갑니다")
    except Exception as e:
        print(f"  [DEBUG] param_info 오류: {e}")

    return today_total, avg


def _read_avg_param_info(page: Page) -> float | None:
    """현재 2-8 화면 '평균 입소자 수 계산' param-info 에서 평균 입소자 수를 읽는다.

    ★2026-07-28 케어포 개편 이후 실측 문구:
      '입소자 합계(1438명) ÷ 급여제공일(25일) = 57.52 값을 반올림하여 평균 입소자 수는 <b>58</b>명 입니다.'
      (개편 전은 '= 59.92 값의' 였다 → '값의'만 찾던 정규식이 조용히 실패해 전월평균이 폴백값으로 나갔다.)

    ★같은 화면에 **숫자 없는 일반 안내문**('입소자 합계 ÷ 급여제공일 값을 반올림하여 계산합니다.')이
      먼저 나온다. 첫 매칭을 그대로 쓰면 늘 None 이 된다 → 후보를 모두 모아 숫자가 있는 것을 고른다.
    """
    infos = page.evaluate("""(() => {
        return [...document.querySelectorAll('[param-info],[data-param-info]')]
            .map(el => el.getAttribute('param-info') || el.getAttribute('data-param-info') || '')
            .filter(s => s.includes('급여제공일') || s.includes('평균 입소자'));
    })()""") or []
    for s in infos:
        m = re.search(r"=\s*([\d]+(?:\.[\d]+)?)\s*값", s)   # '값의'·'값을' 모두 허용
        if m:
            return float(m.group(1))
    return None


def scrape_prev_month_avg(page: Page, target: date) -> float | None:
    """2-8 화면을 직전 달로 이동해(reloadPage) 전월 최종 평균 입소자를 읽는다.

    ★ mm 은 반드시 2자리('06'). 1자리('6')면 케어포가 엉뚱한 값을 반환한다(실측 2026-07: '6'→55.81, '06'→59.92).
    전월은 마감돼 있어 이 값이 곧 '최종' 평균이다. 실패 시 None(보고는 계속되게).
    """
    y, m = target.year, target.month - 1
    if m == 0:
        y, m = y - 1, 12
    # 순간적 로딩 지연·팝업으로 한 번에 못 읽는 경우가 있어 재시도(전월값은 절대 빠지면 안 됨).
    for attempt in range(3):
        try:
            page.evaluate(f"reloadPage({{'yy':'{y}','mm':'{m:02d}'}})")
            page.wait_for_load_state("networkidle", timeout=20000)
            page.wait_for_timeout(2000 + attempt * 1500)
            _close_popups(page)
            page.wait_for_timeout(500)
            v = _read_avg_param_info(page)
            if v is not None and v > 0:
                return v
        except Exception as e:
            print(f"  [DEBUG] 전월({y}.{m:02d}) 평균 수집 시도{attempt + 1} 실패: {e}")
        page.wait_for_timeout(1000)
    print(f"  [WARN] 전월({y}.{m:02d}) 평균 3회 시도 실패 → 폴백값 사용 예정")
    return None


def _click_drive_record_tab(page: Page) -> None:
    """운행기록(필요시) 탭 클릭."""
    page.evaluate("""
        (() => {
            const els = Array.from(document.querySelectorAll('button, input[type="button"], a, td, th, li, span'));
            for (const el of els) {
                const txt = (el.textContent || el.value || '').trim();
                if (txt.includes('운행기록')) {
                    el.click();
                    return true;
                }
            }
            return false;
        })()
    """)
    page.wait_for_timeout(1500)


def _click_maintenance_tab(page: Page) -> None:
    """정비기록(필요시) 탭 클릭."""
    page.evaluate("""
        (() => {
            const els = Array.from(document.querySelectorAll('button, input[type="button"], a, td, th, li, span'));
            for (const el of els) {
                const txt = (el.textContent || el.value || '').trim();
                if (txt.includes('정비기록')) {
                    el.click();
                    return true;
                }
            }
            return false;
        })()
    """)
    page.wait_for_timeout(1500)


def scrape_car_oil_change(page: Page, default_interval: int = 8000) -> dict:
    """
    정비기록 탭에서 최신 엔진오일 교환 기록 추출.
    반환: {"oilDate": "2026-02-06", "oilKm": 40567, "oilNextKm": 48567}
    기록 없으면 {}
    """
    # ★기본 화면은 최근분만 보여 옛 오일교환을 놓친다(2026-07 서구 31머2741: 실제 25.12.16인데 None이 나왔다).
    #   정비일 범위를 넓게 채우고 '조회'해 전체이력을 띄운 뒤 읽는다(collect_car_maintenance 와 동일 방식).
    try:
        s0, e0 = "2023.01.01", date.today().strftime("%Y.%m.%d")
        filled = page.evaluate(
            """([s,e])=>{
              const m=document.getElementById('mask_div'); if(m) m.style.display='none';
              let sec=null;
              document.querySelectorAll('div,section,form').forEach(d=>{
                const t=d.textContent||'';
                if(!sec && t.includes('정비구분') && t.includes('정비내역')
                   && d.querySelectorAll('input').length>=2 && d.querySelectorAll('input').length<=6) sec=d;
              });
              if(!sec) return false;
              const ins=Array.from(sec.querySelectorAll('input')).filter(i=>i.getBoundingClientRect().width>0);
              if(ins.length<2) return false;
              ins[0].value=s; ins[0].dispatchEvent(new Event('change',{bubbles:true}));
              ins[1].value=e; ins[1].dispatchEvent(new Event('change',{bubbles:true}));
              const b=Array.from(sec.querySelectorAll('button,a,span,div,input[type=button]'))
                .find(x=>(x.textContent||x.value||'').trim()==='조회');
              if(b) b.click();
              return true;
            }""", [s0, e0])
        if filled:
            page.wait_for_timeout(2500)
    except Exception:
        pass
    # 정비기록이 <tr>/<td> 테이블이 아닌 커스텀 구조라 innerText에서 직접 파싱
    body = page.evaluate("document.body.innerText")
    # 보이지 않는 제어문자 제거 (U+200E 등)
    body = re.sub(u"[​-‏  ﻿]", "", body)
    lines = [l.strip() for l in body.split('\n')]

    # 레코드 = 날짜(YYYY.MM.DD) 줄부터 다음 날짜 줄(또는 '조회' 구분) 전까지
    date_pat = re.compile(r'^\d{4}\.\d{2}\.\d{2}$')
    records: list[str] = []
    cur: list[str] | None = None
    for line in lines:
        if date_pat.match(line):
            if cur:
                records.append(' '.join(cur))
            cur = [line]
        elif cur is not None:
            if line == '조회':
                records.append(' '.join(cur))
                cur = None
            elif line:
                cur.append(line)
    if cur:
        records.append(' '.join(cur))

    # 오일 교환/교체 '완료' 기록만 인식 — 지점마다 표현이 다양함:
    #  '엔진오일'/'엔진 오일'/'오일', '교환'/'교체', 띄어쓰기 유무, Km/km 대소문자 등.
    #  ⚠️ '엔진오일 필요교체까지 849km'·'엔진오일교체필요' 같은 점검 예고(아직 안 함)는 제외해야 함.
    #     → '필요교체/교체필요/엔진오일필요' 문구가 있고, '완료·다음교체주기·교환(Nkm)' 같은
    #        실제 교환 신호가 없으면 점검 메모로 보고 건너뛴다.
    def _is_real_change(r):
        # ★2026-07-27 서구 전체이력 검수로 확정. '오일 언급 + 아무 교환/교체'는 오판한다:
        #   (오탐) "에어컨필터/와이퍼/타이어 교체 … 엔진오일 점검·확인" → 오일교환 아님
        #   (누락) "엔진오일/에어크리너/오일필터/…/교환" 슬래시 나열은 오일-교환이 안 붙어 놓침
        d = r.replace(' ', '')
        if '오일' not in d:
            return False
        # (1) '(엔진)오일 [주행거리] 교환/교체' — ★오일과 교환 사이에 km(66,500km)가 끼어도 인정
        #     (31머2741 25.12.16 라이브 "엔진오일 66,500km 교환 …차후 74,500km 교환필요"를 놓치던 근본원인).
        #     같은 기록에 '엔진오일 점검'이 섞여도 교환 우선(둔산 3318). '차후/다음 …오일…교환'(다음교환 예고) 제외.
        #     '오일 교체 주기확인/필요'(예고)도 제외.
        for m in re.finditer(r'(?:엔진)?오일[\d,\.km]*교([환체])', d):
            pre = d[max(0, m.start() - 8):m.start()]
            if '차후' in pre or '다음' in pre:
                continue
            if m.group(1) == '체' and d[m.end():m.end() + 6].startswith(('주기확인', '필요')):
                continue
            return True
        # (2) 슬래시/공백 나열에 '엔진오일' 항목 + (오일과 안 붙은) '교환'. 오일 점검·확인·보충이면 제외,
        #     '교환'은 '차후/다음 …교환'(다음교환 예고)이 아닌 것만.
        if '엔진오일' in d and not re.search(r'오일(?:점검|확인|보충)', d):
            for m in re.finditer(r'교환', d):
                pre = d[max(0, m.start() - 8):m.start()]
                if '차후' not in pre and '다음' not in pre:
                    return True
        return False
    oil_rows = [r for r in records if _is_real_change(r)]
    if not oil_rows:
        return {}

    # 최신 기록 = 첫 번째 (내림차순 정렬 기준)
    row_text = oil_rows[0]
    print(f"  [OIL] 최신 오일 기록: {row_text[:150]}")

    date_m = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', row_text)
    oil_date = f"{date_m.group(1)}-{date_m.group(2)}-{date_m.group(3)}" if date_m else None

    # 교환시 주행거리 — 여러 표현을 순차 시도 (앞쪽일수록 우선):
    #  '현재 98,956' / '현 주행거리 80,829' / '(엔진)오일 교환·교체(완료) 67,000' / '교체 …NNKm'
    #  '차후·다음'은 다음주기라 제외(아래에서 별도 처리).
    km_m = (re.search(r'현재\s*([\d,]+)', row_text)
            or re.search(r'현\s*주행\s*거리\s*([\d,]+)', row_text)
            # '엔진오일 66,500km 교환'처럼 오일과 교환 사이에 주행거리가 낀 형식(31머2741). 차후/다음 예고 제외.
            or re.search(r'(?<!차후)(?<!차후\s)(?<!다음)(?<!다음\s)(?:엔진\s*)?오일\s*([\d,]{4,})\s*[kK][mM]\s*교[환체]', row_text)
            or re.search(r'(?<!차후)(?<!차후\s)(?<!다음)(?<!다음\s)(?:엔진\s*)?오일\s*교[환체]\s*(?:완료|시)?\s*[\(（]?\s*([\d,]+)', row_text)
            or re.search(r'교[환체]\s*(?:완료|시)?\s*([\d,]+)\s*[kK][mM]', row_text))
    oil_km = int(km_m.group(1).replace(',', '')) if km_m else None

    # 다음 교환/교체 주기 — '다음 교체주기 106,956' / '다음 주기 …' / '차후 (엔진)오일 교환·교체 88,829'
    next_km_m = (re.search(r'다음\s*교[환체]\s*주기\s*([\d,]+)', row_text)
                 or re.search(r'다음\s*주기\s*([\d,]+)', row_text)
                 or re.search(r'차후\s*(?:엔진\s*)?오일\s*교[환체]\s*([\d,]+)', row_text)
                 # '차후 74,500km 교환필요'처럼 차후 뒤에 주행거리가 바로 오는 형식(31머2741).
                 or re.search(r'차후\s*(?:엔진\s*오일\s*)?([\d,]{4,})\s*[kK][mM]', row_text))
    if next_km_m:
        oil_next_km = int(next_km_m.group(1).replace(',', ''))
    elif oil_km is not None:
        oil_next_km = oil_km + default_interval
    else:
        oil_next_km = None

    # 교환 km를 못 찾았지만 다음 교환 km는 있으면 역산으로 추정
    if oil_km is None and oil_next_km is not None:
        oil_km = oil_next_km - default_interval

    result = {}
    if oil_date:
        result['oilDate'] = oil_date
    if oil_km is not None:
        result['oilKm'] = oil_km
    if oil_next_km is not None:
        result['oilNextKm'] = oil_next_km
    return result


def scrape_car_mileage(page: Page) -> dict[str, int]:
    """
    2-4 차량관리 화면에서 차량별 최신 누적 주행거리 추출.
    g-tf[data-info] → carmgno + carnumb 추출 → 각 차량 클릭 → 운행기록 탭 → 계기판 첫 행 마지막 숫자.
    반환: {차량번호: 누적km}  예) {"121어8045": 92581}
    """
    import json as _json

    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(2000)
    _close_popups(page)
    page.wait_for_timeout(500)

    # g-tf 요소에서 carmgno + carnumb 수집 (HTML에서 직접 파싱 — DOM 변경 전에)
    import json as _json2
    html_src = page.content()
    gtf_re = re.compile(r'<g-tf[^>]+data-key="(\d+)"[^>]+data-info="([^"]+)"')
    raw_cars = []
    for m in gtf_re.finditer(html_src):
        key = m.group(1)
        info_str = m.group(2).replace("&quot;", '"')
        try:
            info = _json2.loads(info_str)
            raw_cars.append({"key": key, "info": info_str})
        except Exception:
            pass

    car_list = []
    seen_keys = set()
    for m in gtf_re.finditer(html_src):
        key = m.group(1)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        info_str = m.group(2).replace("&quot;", '"')
        car_list.append({"key": key, "info": info_str})

    result: dict[str, int] = {}

    for item in car_list:
        try:
            info = _json2.loads(item["info"])
        except Exception:
            continue
        car_no  = info.get("carnumb", "")
        carmgno = item["key"]
        if not car_no or not carmgno:
            continue

        try:
            # reloadPage로 차량 선택
            page.evaluate(f"reloadPage({{'carmgno':'{carmgno}', 'all_car':'Y'}})")
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(1500)

            # 운행기록 탭 클릭
            _click_drive_record_tab(page)
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(1000)

            # 계기판(km) + 운행일: km 패턴 근처 줄에서 날짜 추출
            record = page.evaluate("""
                (() => {
                    const txt = document.body.innerText;
                    const lines = txt.split('\\n');
                    const kmRe = /[\\d,]{4,}\\s*~\\s*[\\d,]{4,}/;
                    const dateRe = /20\\d{2}\\.\\d{2}\\.\\d{2}/;
                    let km = null, date = null;
                    for (let i = 0; i < lines.length; i++) {
                        if (kmRe.test(lines[i]) && !km) {
                            km = lines[i].match(kmRe)[0];
                            for (let j = Math.max(0, i-5); j <= Math.min(lines.length-1, i+5); j++) {
                                const dm = lines[j].match(dateRe);
                                if (dm) { date = dm[0]; break; }
                            }
                            break;
                        }
                    }
                    return { km, date };
                })()
            """)

            car_data: dict = {}
            if record and record.get('km'):
                nums = re.findall(r"[\d,]+", record['km'])
                if len(nums) >= 2:
                    # 출발km ~ 도착km 형식: 더 큰 값이 현재 주행거리
                    car_data['totalKm'] = max(int(n.replace(",", "")) for n in nums)
                elif nums:
                    car_data['totalKm'] = int(nums[0].replace(",", ""))
            if record and record.get('date'):
                # 2026.06.25 → 2026-06-25
                car_data['updatedAt'] = record['date'].replace('.', '-')

            # 정비기록 탭 클릭 → 엔진오일 교환 기록 수집
            _click_maintenance_tab(page)
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(1000)
            oil_data = scrape_car_oil_change(page)
            car_data.update(oil_data)

            if car_data:
                result[car_no] = car_data
        except Exception as e:
            print(f"    [{car_no}] 수집 실패 (건너뜀): {e}")

    return result


def fetch_branch_car_mileage(
    ctmnumb: str,
    branch_name: str,
    headless: bool = True,
) -> dict[str, int]:
    """한 지점의 차량별 최신 누적 주행거리 수집."""
    portal_creds = credentials.get_portal_credentials()
    if not portal_creds:
        raise RuntimeError("케어포 portal 자격증명이 없습니다.")
    portal_id, portal_pw = portal_creds

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(
            http_credentials={"username": portal_id, "password": portal_pw}
        )
        portal_page = ctx.new_page()
        portal_page.goto(PORTAL_URL, wait_until="domcontentloaded")
        portal_page.wait_for_function("typeof login2 === 'function'", timeout=15000)
        portal_page.wait_for_load_state("networkidle", timeout=15000)
        portal_page.wait_for_timeout(3000)

        with ctx.expect_page(timeout=60000) as new_page_info:
            portal_page.evaluate(f"login2('{ctmnumb}')")
        data_page = new_page_info.value
        data_page.wait_for_load_state("domcontentloaded", timeout=30000)
        data_page.wait_for_load_state("networkidle", timeout=30000)

        g_pammgno = extract_g_pammgno(data_page)
        _navigate_spa(data_page, car_manage_url(g_pammgno))

        mileage = scrape_car_mileage(data_page)
        browser.close()

    return mileage


def fetch_branch_attendance(
    ctmnumb: str,
    branch_name: str,
    target_date: date | None = None,
    headless: bool = True,
) -> BranchAttendance:
    """한 지점의 오늘 출석 데이터 수집."""
    target_date = target_date or date.today()

    portal_creds = credentials.get_portal_credentials()
    if not portal_creds:
        raise RuntimeError(
            "케어포 portal 자격증명이 저장되어 있지 않습니다. "
            "먼저 'python setup_credentials.py' 를 실행해 ID/비밀번호를 저장하세요."
        )
    portal_id, portal_pw = portal_creds

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(
            http_credentials={"username": portal_id, "password": portal_pw}
        )
        portal_page = ctx.new_page()

        # 1) portal 진입
        portal_page.goto(PORTAL_URL, wait_until="domcontentloaded")
        portal_page.wait_for_function("typeof login2 === 'function'", timeout=15000)

        # 2) login2 호출 → 새 탭으로 dn.carefor.co.kr 열림
        with ctx.expect_page(timeout=60000) as new_page_info:
            portal_page.evaluate(f"login2('{ctmnumb}')")
        data_page = new_page_info.value
        data_page.wait_for_load_state("domcontentloaded", timeout=30000)
        data_page.wait_for_load_state("networkidle", timeout=30000)

        # 3) g_pammgno 추출
        g_pammgno = extract_g_pammgno(data_page)

        # 4) 1-7 수급자 현황 → 현원(수급중)
        _navigate_spa(data_page, patient_report_url(g_pammgno))
        hyeon_won = scrape_patient_report(data_page)

        # 5) 6-4 시설운영일지 → 일정(출석), 결석 = 현원 - 일정
        _navigate_spa(data_page, daily_center_url(g_pammgno))
        _, iljung = scrape_daily_center(data_page)
        chul_seok = iljung          # 출석 = 일정
        gyeol_seok = hyeon_won - iljung  # 결석 = 현원 - 일정

        # 6) 2-8 월간 입소자 → 현월 월평균 + 전월 최종 평균
        _navigate_spa(data_page, monthly_attend_url(g_pammgno))
        _, avg_attendees = scrape_monthly_attend(data_page, target_date)
        # 전월은 같은 2-8 화면을 직전 달로 돌려 읽는다(reloadPage yy/mm). 현월 읽은 뒤 실행.
        prev_avg_attendees = scrape_prev_month_avg(data_page, target_date)

        browser.close()

        return BranchAttendance(
            name=branch_name,
            ctmnumb=ctmnumb,
            hyeon_won=hyeon_won,
            gyeol_seok=gyeol_seok,
            chul_seok=chul_seok,
            avg_attendees=avg_attendees,
            prev_avg_attendees=prev_avg_attendees,
        )
