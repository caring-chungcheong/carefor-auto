# -*- coding: utf-8 -*-
"""지점 단위 페이지 수집·판정 — 그룹 A(8-7 교육, 8-7-1 보수교육) + 그룹 D(6-3 정기점검).

수급자별 스캔과 달리 팝업 없이 페이지 DOM 텍스트를 그대로 파싱한다.
연도 전환은 페이지 내 reloadPage({'yy':'YYYY'}) 호출.

판정 항목: 5(보수교육) 6(직원교육) 11(재난대응) 13(시설안전)
           16②(정기소독, 부분) 19①(노인인권 교육, 부분)
"""
from __future__ import annotations

import re
from datetime import date, datetime

from src.carefor_client import build_spa_hash, _navigate_spa

DN_BASE = "https://dn.carefor.co.kr/"

PAGES = {
    "edu":       ("left_sub8", "/share/staff/view.staff_education", "8-7.교육일지"),
    "refresher": ("left_sub8", "/share/staff/view.staff_refresher_training", "8-7-1.요양보호사 보수교육"),
    "checks":    ("left_sub6", "/share/safe/view.regularly_check", "6-3.정기점검"),
    "guide":     ("left_sub1", "/patient/view.patient_guide", "1-6.수급자 안내사항/예방접종"),
}

CLOSE_MODAL_JS = """
(() => {
  const btn = Array.from(document.querySelectorAll('div.m_button, .m_button'))
    .find(el => el.textContent.trim() === '창닫기');
  if (btn) btn.click();
  const mask = document.getElementById('mask_div');
  if (mask) mask.style.display = 'none';
})()
"""

GET_TEXT_JS = "(() => { const el = document.querySelector('#r_padding') || document.body; return el.innerText; })()"
GET_YEAR_JS = "(() => { const el = document.querySelector('.datepicker .datearea'); return el ? el.textContent.trim() : ''; })()"


def _goto(page, key: str, g_pammgno: str) -> None:
    type_, view, title = PAGES[key]
    h = build_spa_hash(type_, view, title, g_pammgno)
    _navigate_spa(page, f"{DN_BASE}#{h}")
    page.wait_for_timeout(3500)


def _set_year(page, year: int) -> None:
    cur = page.evaluate(GET_YEAR_JS)
    if str(year) in cur:
        return
    page.evaluate(f"reloadPage({{'yy':'{year}'}})")
    page.wait_for_timeout(3000)


def scrape_branch_pages(page, g_pammgno: str, years: list[int], progress_cb=print) -> dict:
    """세 페이지를 연도별로 순회하며 innerText 원문 수집."""
    out = {"edu": {}, "checks": {}, "refresher": None, "rights": None}

    _goto(page, "edu", g_pammgno)
    for y in years:
        _set_year(page, y)
        out["edu"][str(y)] = page.evaluate(GET_TEXT_JS)
        progress_cb(f"  8-7 교육일지 {y}년 수집")

    _goto(page, "refresher", g_pammgno)
    out["refresher"] = page.evaluate(GET_TEXT_JS)
    progress_cb("  8-7-1 보수교육 수집")

    _goto(page, "checks", g_pammgno)
    for y in years:
        _set_year(page, y)
        out["checks"][str(y)] = page.evaluate(GET_TEXT_JS)
        progress_cb(f"  6-3 정기점검 {y}년 수집")

    # 1-6 직원인권 보호지침 탭 (2026 신설 지표 — 2026년부터만)
    if max(years) >= 2026:
        try:
            _goto(page, "guide", g_pammgno)
            page.evaluate(CLOSE_MODAL_JS)
            page.wait_for_timeout(800)
            page.click(".tabmenu2 li:has-text('직원인권')", timeout=10000)
            page.wait_for_timeout(4000)
            out["rights"] = page.evaluate(
                "(() => { const el = document.querySelector('#tab_div_guide_offer_when_join');"
                " return el ? el.innerText : ''; })()"
            )
            progress_cb("  1-6 직원인권 보호지침 수집")
        except Exception as e:
            out["rights"] = ""
            progress_cb(f"  1-6 직원인권 보호지침 수집 실패: {e}")

    return out


# ---------------- 파싱 ----------------

def parse_edu(text: str) -> dict:
    """교육일지: 회차 레코드([N회] 날짜 + 교육명 + 서명 n/m) + 신규직원 알림."""
    lines = [ln.strip() for ln in text.split("\n")]
    records = []
    for i, ln in enumerate(lines):
        m = re.match(r"^\[(\d+)회\]\s*(\d{4}\.\d{2}\.\d{2})", ln)
        if not m:
            continue
        name, sign = "", None
        for j in range(i + 1, min(i + 6, len(lines))):
            s = lines[j]
            if not s:
                continue
            sm = re.search(r"(\d+)\s*/\s*(\d+)", s)
            if "서명" in s and sm:
                sign = (int(sm.group(1)), int(sm.group(2)))
                break
            if s == "직원 서명":
                continue
            if re.match(r"^\[(\d+)회\]", s):
                break
            if not name and not re.match(r"^\d+\s*/\s*\d+$", s):
                name = s
            elif name and sm and re.match(r"^\d+\s*/\s*\d+$", s):
                sign = (int(sm.group(1)), int(sm.group(2)))
                break
        records.append({"round": int(m.group(1)), "date": m.group(2), "name": name, "sign": sign})

    # 신규직원 교육 기한 알림 (직원명/교육명/입사일/기한 4줄 반복)
    newstaff = []
    try:
        k = lines.index("교육 대상 신규직원")
        seq = [s for s in lines[k:k + 40] if s]
        # 헤더(직원명 교육명 입사일 교육 실시 기한) 이후 4개씩
        hdr = seq.index("교육 실시 기한")
        vals = seq[hdr + 1:]
        for a in range(0, len(vals) - 3, 4):
            nm, edu, join, due = vals[a:a + 4]
            dm = re.search(r"(\d{4}\.\d{2}\.\d{2})", due)
            jm = re.search(r"(\d{4}\.\d{2}\.\d{2})", join)
            if not (dm and jm):
                break
            newstaff.append({"name": nm, "edu": edu, "join": jm.group(1), "due": dm.group(1)})
    except ValueError:
        pass
    return {"records": records, "newstaff": newstaff}


def parse_checks(text: str) -> dict:
    """정기점검: 소방 12개월 + 약품 4분기 + 소독 4분기 작성 여부."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    # 마지막 '4분기' 위치 (소독 헤더 끝) 이후 상태 토큰 20개
    idxs = [i for i, s in enumerate(lines) if s == "4분기"]
    fire, med, dis = [], [], []
    if len(idxs) >= 2:
        statuses = []
        for s in lines[idxs[-1] + 1:]:
            if s in ("작성", "미작성", "-"):
                statuses.append(s == "작성")
                if len(statuses) == 20:
                    break
            elif len(statuses) > 0 and s not in ("작성", "미작성", "-"):
                break
        if len(statuses) == 20:
            fire, med, dis = statuses[:12], statuses[12:16], statuses[16:20]
    return {"fire": fire, "med": med, "disinfect": dis}


def parse_refresher(text: str) -> dict:
    """보수교육: 대상/작성 카운트 + 직원별 상태."""
    target = done = None
    m = re.search(r"대상 직원 수\s*\n\s*(\d+)명", text)
    if m:
        target = int(m.group(1))
    m = re.search(r"작성 직원 수\s*\n\s*(\d+)명\s*/\s*(\d+)명", text)
    if m:
        done = int(m.group(1))
    rows = []
    lines = [ln.strip() for ln in text.split("\n")]
    for i, ln in enumerate(lines):
        if ln in ("작성", "미작성", "연중 퇴사", "연중퇴사"):
            # 역방향으로 이름 찾기: [연번, 이름, 성별, 생년, 입사, 퇴사, 직종..., 대상여부, 상태]
            back = [s for s in lines[max(0, i - 12):i] if s]
            name = ""
            for b in range(len(back) - 1, -1, -1):
                if back[b] in ("대상", "비대상"):
                    # 대상여부 앞쪽에서 성별 위치 기준으로 이름 추정
                    for c in range(b - 1, -1, -1):
                        if back[c] in ("남", "여") and c >= 1:
                            name = back[c - 1]
                            break
                    break
            if name:
                rows.append({"name": name, "status": ln})
    return {"target": target, "done": done, "rows": rows}


def parse_rights(text: str) -> dict:
    """1-6 직원인권 보호지침 탭: 수급자별 [현황, 이름, 급여개시일, 제공일|퇴소(날짜)]."""
    lines = [ln.strip() for ln in text.split("\n")]
    date_re = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")

    done = total = None
    for ln in lines[:40]:
        m = re.match(r"^(\d+)\s*/\s*(\d+)$", ln)
        if m:
            done, total = int(m.group(1)), int(m.group(2))
            break

    rows = []
    i = 0
    while i < len(lines):
        if lines[i].isdigit():
            seq = lines[i + 1:i + 8]
            if len(seq) >= 5 and seq[0] in ("수급중", "퇴소", "보류", "대기", "입소대기"):
                status, group, name, grade, start = seq[0], seq[1], seq[2], seq[3], seq[4]
                if date_re.match(start):
                    provided = left_before = None
                    nxt = seq[5] if len(seq) > 5 else ""
                    if date_re.match(nxt):
                        provided = nxt
                    else:
                        mm = re.match(r"퇴소\((\d{4}\.\d{2}\.\d{2})\)", nxt)
                        if mm:
                            left_before = mm.group(1)
                    rows.append({"status": status, "name": name, "grade": grade,
                                 "start": start, "provided": provided, "left_before": left_before})
                    i += 6
                    continue
        i += 1
    return {"done": done, "total": total, "rows": rows}


# ---------------- 판정 ----------------

def _half_of(d: str) -> str:
    return "상반기" if int(d[5:7]) <= 6 else "하반기"


def analyze_branch_pages(data: dict, cutoff: str, today: date | None = None) -> dict:
    today = today or date.today()
    cut = datetime.strptime(cutoff, "%Y.%m.%d").date()
    years = sorted(int(y) for y in data.get("edu", {}).keys())

    edu_parsed = {y: parse_edu(data["edu"][str(y)]) for y in years}
    chk_parsed = {y: parse_checks(data["checks"].get(str(y), "")) for y in years}
    refresher = parse_refresher(data.get("refresher") or "")

    # ---- 항목 11: 재난대응훈련 반기별 (기준일 5/1, 11/1) ----
    disaster_miss = []
    for y in years:
        recs = [r for r in edu_parsed[y]["records"] if "재난" in r["name"]]
        for half, due, lo, hi, end in (
            ("상반기", date(y, 5, 1), f"{y}.01.01", f"{y}.06.30", date(y, 6, 30)),
            ("하반기", date(y, 11, 1), f"{y}.07.01", f"{y}.12.31", date(y, 12, 31)),
        ):
            if today < due or end < cut:
                continue
            if not any(lo <= r["date"] <= hi for r in recs):
                disaster_miss.append(f"{y} {half}")

    # ---- 항목 19①: 노인인권 교육 반기별 ----
    rights_miss = []
    rights_note = []
    for y in years:
        recs = [r for r in edu_parsed[y]["records"] if "노인인권" in r["name"] or "학대" in r["name"]]
        for half, lo, hi, end in (
            ("상반기", f"{y}.01.01", f"{y}.06.30", date(y, 6, 30)),
            ("하반기", f"{y}.07.01", f"{y}.12.31", date(y, 12, 31)),
        ):
            if end < cut:
                continue
            has = any(lo <= r["date"] <= hi for r in recs)
            if not has:
                if end < today:
                    rights_miss.append(f"{y} {half}")
                elif date(today.year, today.month, 1) > datetime.strptime(lo, "%Y.%m.%d").date():
                    rights_note.append(f"{y} {half} 미작성(진행중)")
        # 서명 미완: n/m 합계 기준
        for r in recs:
            if r["sign"] and r["sign"][1] - r["sign"][0] > 0:
                rights_note.append(f"{r['date']} 서명 {r['sign'][0]}/{r['sign'][1]}")

    # ---- 항목 6: 운영규정 교육(연1회) + 급여제공지침교육(연1회) + 신규직원 7일 ----
    edu6_miss = []
    for y in years:
        if date(y, 12, 31) < cut:
            continue
        recs = edu_parsed[y]["records"]
        if not any("운영규정" in r["name"] for r in recs):
            edu6_miss.append(f"{y} 운영규정 교육 없음" if y < today.year else f"{y} 운영규정 교육 미실시(진행중)")
        if not any("급여제공지침" in r["name"] for r in recs):
            edu6_miss.append(f"{y} 급여제공지침교육 없음" if y < today.year else f"{y} 급여제공지침교육 미실시(진행중)")
    # 신규직원 교육 기한 초과 (당해연도 알림)
    cur_ns = edu_parsed.get(today.year, {}).get("newstaff", [])
    overdue_ns = [
        f"{n['name']}({n['edu']} 기한 {n['due']})"
        for n in cur_ns
        if datetime.strptime(n["due"], "%Y.%m.%d").date() < today
    ]
    edu6_miss += ["신규직원 기한초과: " + s for s in overdue_ns]
    edu6_cur = [s for s in edu6_miss if "진행중" not in s]

    # ---- 항목 5: 보수교육 ----
    ref_miss = [r["name"] for r in refresher["rows"] if r["status"] == "미작성"]
    ref_target, ref_done = refresher.get("target"), refresher.get("done")

    # ---- 항목 13: 소방시설 월 1회 (매월 28일 기준) ----
    fire_miss = []
    for y in years:
        fire = chk_parsed[y]["fire"]
        if not fire:
            fire_miss.append(f"{y}년 데이터 파싱 실패")
            continue
        for mth in range(1, 13):
            m_end = date(y, mth, 28)
            if m_end < cut or m_end > today:
                continue
            if not fire[mth - 1]:
                fire_miss.append(f"{y}.{mth:02d}")

    # ---- 항목 16②: 정기소독 분기별 ----
    dis_miss = []
    q_ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    for y in years:
        dis = chk_parsed[y]["disinfect"]
        if not dis:
            dis_miss.append(f"{y}년 데이터 파싱 실패")
            continue
        for q, (mm, dd) in q_ends.items():
            q_end = date(y, mm, dd)
            if q_end < cut or q_end > today:
                continue
            if not dis[q - 1]:
                dis_miss.append(f"{y} {q}분기")

    # ---- 항목 7: 직원인권 보호지침 (2026 신설 — 2026년부터) ----
    rights = parse_rights(data.get("rights") or "")
    r7_missing, r7_late = [], []
    for r in rights["rows"]:
        if r["left_before"]:
            continue  # 안내일 이전 퇴소자 제외 (사용자 확정)
        if not r["provided"]:
            r7_missing.append(f"{r['name']}({r['status']})")
        elif r["start"] >= "2026" and r["provided"] > r["start"]:
            # 2026년 급여개시 수급자: 개시일까지 안내돼 있어야 (미리 안내는 정상)
            r7_late.append(f"{r['name']} 개시{r['start']}→제공{r['provided']}")

    def st(miss):
        return "양호" if not miss else "미흡"

    item_results = {}
    if data.get("rights"):
        parts = []
        if rights["done"] is not None:
            parts.append(f"완료 {rights['done']}/{rights['total']}명")
        if r7_missing:
            parts.append("미제공: " + ", ".join(r7_missing))
        if r7_late:
            parts.append("개시 후 지연제공: " + ", ".join(r7_late))
        if not r7_missing and not r7_late:
            parts.append("전 수급자 제공 확인 (안내 전 퇴소자 제외)")
        item_results["7"] = {
            "status": st(r7_missing + r7_late),
            "detail": "2026년 기준 — " + " · ".join(parts),
        }

    item_results |= {
        "5": {
            "status": st(ref_miss),
            "detail": (f"대상 {ref_target}명 중 작성 {ref_done}명"
                       + (f", 미작성: {', '.join(ref_miss)}" if ref_miss else " — 전원 이수/작성")),
        },
        "6": {
            "status": st(edu6_cur),
            "detail": ("; ".join(edu6_miss) or "운영규정·급여제공지침 교육 연 1회 충족")
                      + " (①지침 12항목 비치는 수기 확인)",
        },
        "11": {
            "status": st(disaster_miss),
            "detail": ("누락: " + ", ".join(disaster_miss)) if disaster_miss else "반기별 재난대응훈련 실시 확인",
        },
        "13": {
            "status": st(fire_miss),
            "detail": ("소방점검 누락: " + ", ".join(fire_miss)) if fire_miss else "매월 소방시설 점검 입력 확인",
        },
        "16": {
            "status": st(dis_miss),
            "detail": "[부분판정: ②정기소독만] "
                      + (("누락: " + ", ".join(dis_miss)) if dis_miss else "분기별 정기소독 입력 확인")
                      + " (①③ 일일점검은 2차 구현 예정)",
        },
        "19": {
            "status": st(rights_miss),
            "detail": "[부분판정: ①교육일지만] "
                      + (("누락: " + ", ".join(rights_miss)) if rights_miss else "반기별 노인인권 교육 확인")
                      + (" / " + "; ".join(rights_note) if rights_note else "")
                      + " (②안내사항·③기록지는 3~4차 구현 예정)",
        },
    }

    return {
        "item_results": item_results,
        "detail": {
            "edu_records": {y: edu_parsed[y]["records"] for y in years},
            "newstaff": cur_ns,
            "refresher": refresher,
            "checks": {y: chk_parsed[y] for y in years},
            "rights": rights,
        },
    }
