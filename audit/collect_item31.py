# -*- coding: utf-8 -*-
"""항목 31① 등급 유지·호전율 — 케어포 1-9 수급자 등급 변동 현황에서 자동 수집.

기준(items.py)
  ① 6개월 이상 연속 급여제공 후 기간 내 갱신 등급판정을 받은 수급자 중,
     최근 갱신 등급과 직전 등급 비교 시 유지·호전된 비율×100 (소수점 첫째자리 반올림)
     75% 이상 1점 / 50~75% 미만 0.75점 / 해당 수급자 없으면 '해당없음' 제외
     〔적용기간: 2024.1월 ~ 2025.12월〕

화면(실측 2026-08-02)
  view: /share/patient/view.patient_level_report  (좌측 1-9)
  조회구간 input[name=s_date] ~ input[name=e_date] + '조회' 버튼 (YYYY.MM.DD)
  표: 연번 · 수급자명 · 이전 등급 · 갱신 등급 · 갱신일 · 결과(유지/호전/악화)
  하단: "유지·호전율  NN%  점"   ← 케어포가 직접 계산해 준다(우리가 다시 세지 않는다)

★적용기간은 지점 평가연도마다 다르다 — items.eval_period() 로 잡는다.
  2026년 평가 지점 → 2024.01.01~2025.12.31 / 2027년 평가 지점(2025년 개소) → 2025.01.01~2026.12.31
  기간을 2026년 기준으로 잘못 잡으면 2027년 평가 지점이 '대상 0명'으로 나와 판정이 뒤집힌다(실측).
★기관 개소 전 데이터는 없으므로 s_date 는 max(개소일, 적용기간 시작) 로 잡는다.
"""
from __future__ import annotations

import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

from src.carefor_client import build_spa_hash, _navigate_spa

LEVEL_VIEW = "/share/patient/view.patient_level_report"
DN = "https://dn.carefor.co.kr/"

# 평가 적용기간
PERIOD_START = "2024.01.01"
PERIOD_END = "2025.12.31"

_CLOSE = """()=>{let n=0;document.querySelectorAll('button,a,span,input[type=button]').forEach(e=>{
  const t=(e.value||e.innerText||'').trim();
  if((t==='창닫기'||t==='닫기')&&e.offsetParent!==null){e.click();n++;}});return n;}"""


def _close_modals(page, rounds: int = 3):
    for _ in range(rounds):
        if not page.evaluate(_CLOSE):
            break
        page.wait_for_timeout(700)


def _set_period(page, s: str, e: str):
    page.evaluate("""(a)=>{
      const sd=document.querySelector('input[name=s_date]'), ed=document.querySelector('input[name=e_date]');
      if(sd) sd.value=a.s; if(ed) ed.value=a.e;
      const btn=[...document.querySelectorAll('.m_button,button,a,span,input[type=button]')]
        .find(x=>((x.value||x.innerText||'').trim()==='조회') && x.offsetParent!==null);
      if(btn) btn.click();}""", {"s": s, "e": e})
    page.wait_for_timeout(4500)


def scrape_level_report(page, g_pammgno, cutoff: str | None = None,
                        progress=print, branch_name: str | None = None) -> dict:
    """1-9 를 평가 적용기간으로 조회해 유지·호전율과 명단을 가져온다.

    ★적용기간은 지점 평가연도마다 다르다 — 서구는 2025년 개소라 2027년 평가 대상이라
      2025.01.01~2026.12.31 로 봐야 한다(회원님 확정 2026-08-02).
    """
    start, end = PERIOD_START, PERIOD_END
    if branch_name:
        from .items import eval_period
        start, end = eval_period(branch_name)
    s = max(cutoff or start, start)
    _navigate_spa(page, f"{DN}#{build_spa_hash('left_sub1', LEVEL_VIEW, '1-9.수급자 등급 변동 현황', g_pammgno)}")
    page.wait_for_timeout(5000)
    _close_modals(page)
    _set_period(page, s, end)
    _close_modals(page)

    body = page.evaluate("document.body.innerText")
    # ★대상자가 없으면 케어포가 퍼센트 대신 '제외'라고 쓴다(서구 실측) — 조회 실패와 구분해야 한다
    excluded = bool(re.search(r"유지·호전율\s*제외", body))
    m = re.search(r"유지·호전율\s*([\d.]+)\s*%", body)
    rows = []
    for line in body.split("\n"):
        mm = re.match(r"^\s*(\d+)\t([^\t]+)\t([^\t]*)\t([^\t]*)\t([\d.]{8,10})\t(유지|호전|악화)", line)
        if mm:
            _, name, prev, cur, dt, res = mm.groups()
            rows.append({"name": name.strip(), "prev": prev.strip(),
                         "cur": cur.strip(), "date": dt.strip(), "result": res})
    rate = float(m.group(1)) if m else None
    progress(f"  1-9 등급변동: {s}~{end} · 대상 {len(rows)}명 · "
             f"유지·호전율 {'제외(해당없음)' if excluded else rate}")
    return {"period": [s, end], "rate": rate, "rows": rows, "excluded": excluded}


def judge_item31(data: dict) -> dict:
    """31① 판정. 75% 이상만 '양호'(자동 만점) — 50~75%는 부분점수라 수기 입력이 필요하다.

    ★'주의'로 두는 이유: autoVal 은 '양호'일 때만 만점을 넣는다. 0.75점을 자동으로 넣을
      수단이 없으므로 채점자가 직접 넣도록 detail 에 점수를 명시한다.
    """
    rate, rows = data.get("rate"), data.get("rows") or []
    period = " ~ ".join(data.get("period") or [])
    # 적용기간 내 대상자가 0명인 경우(케어포 1-9 하단이 퍼센트 대신 '제외'로 표시).
    # 기준 문언은 "해당 수급자 없으면 '해당없음' 제외 처리"지만,
    # ★본부 방침(회원님 확정 2026-08-02)에 따라 **미흡(0점)** 으로 처리한다.
    if data.get("excluded") or not rows:
        return {"status": "미흡", "sub_status": {"①": "미흡"},
                "detail": (f"[①등급 유지·호전율] 적용기간 내 갱신 등급판정 수급자 0명 "
                           f"(케어포 1-9 하단 '제외' 표시) · 조회 {period} → "
                           f"**0점**(본부 방침: 해당없음 제외가 아니라 미흡 처리)")}
    if rate is None:
        return {"status": "주의", "sub_status": {"①": "주의"},
                "detail": (f"[①등급 유지·호전율] 대상 {len(rows)}명인데 1-9 하단 산출값을 못 읽음 "
                           f"— 수기 확인 ({period})")}

    keep = [r for r in rows if r["result"] in ("유지", "호전")]
    worse = [r for r in rows if r["result"] == "악화"]
    base = (f"[①등급 유지·호전율] {rate:g}% — 대상 {len(rows)}명 중 유지·호전 {len(keep)}명"
            f"(악화 {len(worse)}명) · 조회 {period} · 케어포 1-9 하단 산출값")
    if worse:
        base += " · 악화: " + ", ".join(f"{r['name']}({r['prev']}→{r['cur']})" for r in worse[:6])
        if len(worse) > 6:
            base += f" 외 {len(worse) - 6}명"

    if rate >= 75:
        return {"status": "양호", "sub_status": {"①": "양호"}, "detail": base + " → 1점"}
    if rate >= 50:
        return {"status": "주의", "sub_status": {"①": "주의"},
                "detail": base + " → **0.75점**(50~75% 구간 · 부분점수라 채점 시 직접 입력)"}
    return {"status": "미흡", "sub_status": {"①": "미흡"}, "detail": base + " → 0점(50% 미만)"}
