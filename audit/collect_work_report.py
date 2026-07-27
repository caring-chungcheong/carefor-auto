# -*- coding: utf-8 -*-
"""8-4 출퇴근 및 근무관리 → 직원별 '근무일지' 작성 여부 점검.

대상 직종: 시설장(관리책임자)·사무원·간호(조무)사·사회복지사 (요양보호사·운전사·조리원 제외).
대상 기간: 지점 개소일(9-1 기관 지정일자 = items.BRANCH_CUTOFFS) ~ 오늘. 직원별로는 입사일 이후.
퇴사자: 8-4 직원목록 기본이 재직자만 → 자동 제외.

판정(달력 셀) — ★근무일지는 '무조건 작성'이 아니라 근무일정과 대조해야 한다(사용자 확정 2026-07-27).
  근무일정 있음  = 셀 텍스트에 '(근) HH:MM~HH:MM'  ← 이 날만 작성 대상
  출퇴근 기록    = '(출) ...'
  근무일지 작성  = '근무일지' 버튼 class btn_type6_4 (미작성은 btn_type6_5)
  → 누락 = 근무일정 있음 and 근무일지 미작성
  → 일요일·공휴일(빨간날)·휴무일·토요일은 일정이 없으면 대상 아님(미작성이 정상).
     단 그 날에도 근무일정이 잡혀 있으면(=근무자) 대상에 포함된다.
  → 일정 없이 출퇴근 기록만 있는 날은 누락으로 세지 않고 'no_sched'로 따로 표기(일정 누락 의심).

산출물: audit_results/work_report_<지점키>.json (개인정보 → 커밋 금지, gitignore됨)

사용:
  py -X utf8 -m audit.collect_work_report --branch 둔산점
  py -X utf8 -m audit.collect_work_report --all
  py -X utf8 -m audit.collect_work_report --branch 둔산점 --months 2   # 최근 2개월만(월 정기점검용)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

from src.carefor_client import build_spa_hash, _navigate_spa, extract_g_pammgno
from src.config import Config, config_path
from .explore_pages import login
from .items import BRANCH_CUTOFFS

OUT_DIR = Path(__file__).resolve().parent.parent / "audit_results"
WORK = ("left_sub8", "/share/staff/view.staff_work_manage", "8-4.출퇴근 및 근무관리")

# 대상 직종(담당직종 텍스트 부분일치). 간호조무사도 '간호'로 잡힘.
TARGET_JOB_RE = re.compile(r"시설장|관리책임자|사무원|간호|사회복지사|복지사")
# 대상에서 뺄 직종(위 정규식에 걸릴 수 있는 것 방어)
SKIP_JOB_RE = re.compile(r"요양보호사|운전|조리|위생|대표자")
# 기관 점검용 가상 계정
EXCLUDE_STAFF = {"관리팀", "평가자"}

STAFF_JS = """
(() => [...document.querySelectorAll('#staff_list_table tr.cr')].map(tr => {
  let d = {}; try { d = JSON.parse(tr.getAttribute('data-info')) || {}; } catch (e) { d = {}; }
  const tds = tr.querySelectorAll('td');
  return {no: d.stmmgno, name: d.stmname, stat: d.stmstat,
          indt: d.stmindt, otdt: d.stmotdt,
          job: (tds[2] ? tds[2].innerText : '').trim()};
}).filter(x => x.no))()
"""

# 달력 셀 파싱 + 현재 표시중인 연월(레이스 방지용)
CAL_JS = """
(() => {
  const cal = document.querySelector('input[data-type=monthCal]');
  const shown = cal ? (cal.value || '') : '';
  const t = document.querySelector('.tbl_wsch3');
  if (!t) return {shown, days: null};
  const days = [...t.querySelectorAll('td[data-rel=work_manage_td]')].map(td => {
    const btn = td.querySelector('[div-name=staff_daily_commute]');
    const cls = btn ? btn.className : '';
    // ★날짜는 '근무일지' 버튼의 sdcyymm+sdcdddd 에서 뽑는다.
    //   td 자체의 param-info 'date'는 근무일정이 있는 날엔 없어서(구조가 다름) 쓰면 안 된다.
    const bp = btn ? (btn.getAttribute('param-info') || '') : '';
    const my = bp.match(/'sdcyymm':'(\\d{6})'/), md = bp.match(/'sdcdddd':'(\\d{2})'/);
    let dt = (my && md) ? my[1] + md[1] : '';
    if (!dt) {
      const m2 = (td.getAttribute('param-info') || '').match(/'date':'(\\d{8})'/);
      dt = m2 ? m2[1] : '';
    }
    // 화면 텍스트만(주석 안 '작성완료' 제외) — 일정/출퇴근 유무 판정용
    const txt = td.innerText.replace(/\\s+/g, ' ').trim();
    return {date: dt, written: /btn_type6_4/.test(cls), cls, text: txt};
  }).filter(x => x.date);
  return {shown, days};
})()
"""


def _ym_range(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _parse_dt(s: str):
    """'YYYYMMDD' 또는 'YYYY.MM.DD' → date (없으면 None)."""
    if not s:
        return None
    s = s.replace(".", "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def scrape_month(page, stmmgno, y: int, m: int, progress=print) -> list | None:
    """해당 직원·월의 달력 셀 반환. 월 전환 실패(레이스) 시 1회 재시도."""
    want = f"{y}{m:02d}"
    for attempt in (1, 2):
        page.evaluate(f"reloadPage({{'yy':'{y}','mm':'{m:02d}','stmmgno':'{stmmgno}'}})")
        page.wait_for_timeout(2500 if attempt == 1 else 4000)
        r = page.evaluate(CAL_JS)
        days = r.get("days")
        if days and r.get("shown") == want and days[0]["date"][:6] == want:
            return days
    progress(f"    ! {want} 월 전환 실패(건너뜀)")
    return None


def collect_branch(page, branch: str, since: date, until: date, progress=print) -> dict:
    """지점 1곳 수집(since~until). page 는 이미 해당 지점으로 로그인된 상태."""
    staff = page.evaluate(STAFF_JS)
    targets = [s for s in staff
               if s["name"] not in EXCLUDE_STAFF
               and TARGET_JOB_RE.search(s["job"] or "")
               and not SKIP_JOB_RE.search(s["job"] or "")]
    progress(f"  직원 {len(staff)}명 중 대상 {len(targets)}명: "
             + ", ".join(f"{s['name']}({s['job']})" for s in targets))

    out = {"branch": branch, "since": since.isoformat(), "until": until.isoformat(),
           "run_at": date.today().isoformat(), "staff_total": len(staff), "staff": []}
    for s in targets:
        joined = _parse_dt(s["indt"])
        start = max(since, joined) if joined else since
        left = _parse_dt(s["otdt"])
        end = min(until, left) if left else until
        rec = {"name": s["name"], "job": s["job"], "no": s["no"],
               "joined": s["indt"], "left": s["otdt"] or "",
               "from": start.isoformat(), "to": end.isoformat(),
               "months": [], "target_days": 0, "written_days": 0, "missing": [],
               "no_sched": [], "failed_months": []}
        if start > end:
            out["staff"].append(rec)
            continue
        progress(f"  · {s['name']} ({s['job']}) {start:%Y-%m} ~ {end:%Y-%m}")
        for y, m in _ym_range(start, end):
            days = scrape_month(page, s["no"], y, m, progress)
            if days is None:
                rec["failed_months"].append(f"{y}-{m:02d}")
                continue
            mt = mw = 0
            for d in days:
                dt = _parse_dt(d["date"])
                if dt is None or dt < start or dt > end:
                    continue
                txt = d["text"]
                has_sched = "(근)" in txt
                has_commute = "(출)" in txt
                # 셀 상단 라벨(공휴일명·연차·반차 등) 남겨 판단 근거 제공
                label = re.sub(r"근무일지.*$", "", txt).strip()[:40]
                if not has_sched:
                    # 근무일정 없음 = 작성 대상 아님(일요일·공휴일·휴무). 단 출퇴근 기록만 있으면 별도 표기.
                    if has_commute:
                        rec["no_sched"].append({"date": d["date"], "label": label,
                                                "written": d["written"]})
                    continue
                mt += 1
                if d["written"]:
                    mw += 1
                else:
                    rec["missing"].append({"date": d["date"], "label": label,
                                           "sched": True, "commute": has_commute})
            rec["months"].append({"ym": f"{y}-{m:02d}", "target": mt, "written": mw})
            rec["target_days"] += mt
            rec["written_days"] += mw
        progress(f"    → 일정 있는 날 {rec['target_days']}일 / 작성 {rec['written_days']}일 / "
                 f"누락 {len(rec['missing'])}일 / 일정없이 출퇴근만 {len(rec['no_sched'])}일")
        out["staff"].append(rec)
    return out


def run(branch_name: str, months: int | None, today: date, progress=print,
        ym: str | None = None) -> dict:
    cfg = Config.load(config_path())
    b = next(x for x in cfg.branches if x.name == branch_name)
    opened = _parse_dt(BRANCH_CUTOFFS.get(branch_name, "")) or date(2024, 1, 1)
    # 오늘 근무일지는 퇴근 후 작성이 정상 → 어제까지만 판정한다.
    end = today - timedelta(days=1)
    if ym:                       # 특정 월만 (월 정기점검: 전월)
        y, m = int(ym[:4]), int(ym[5:7])
        since = max(opened, date(y, m, 1))
        last = date(y + (m == 12), 1 if m == 12 else m + 1, 1) - timedelta(days=1)
        end = min(end, last)
    elif months:                 # 최근 N개월
        y, m = today.year, today.month
        for _ in range(months - 1):
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        since = max(opened, date(y, m, 1))
    else:                        # 개소일부터 전체
        since = opened
    progress(f"[{branch_name}] 기준일 {since} ~ {end} (오늘 {today} 제외)")

    with sync_playwright() as p:
        browser, page = login(p, b.ctmnumb, headless=True)
        try:
            g = extract_g_pammgno(page)
            t, v, title = WORK
            _navigate_spa(page, f"https://dn.carefor.co.kr/#{build_spa_hash(t, v, title, g)}")
            page.wait_for_timeout(5000)
            data = collect_branch(page, branch_name, since, end, progress)
        finally:
            browser.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # ★월 단위 결과가 개소일~현재 전체 결과를 덮어쓰지 않게 파일명을 분리한다.
    key = branch_name.replace(" ", "_") + (f"_{ym}" if ym else "")
    (OUT_DIR / f"work_report_{key}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    progress(f"  저장: audit_results/work_report_{key}.json")
    return data


def prev_ym(today: date) -> str:
    """전월 'YYYY-MM'."""
    y, m = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    return f"{y}-{m:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--months", type=int, default=None,
                    help="최근 N개월만 점검. 미지정 시 개소일부터 전체")
    ap.add_argument("--ym", default=None,
                    help="특정 월만 점검 YYYY-MM ('prev'=전월). 월 정기점검용")
    a = ap.parse_args()

    cfg = Config.load(config_path())
    names = [x.name for x in cfg.branches] if a.all else [a.branch]
    today = date.today()
    ym = prev_ym(today) if a.ym == "prev" else a.ym
    for n in names:
        # 케어포는 단일 계정 — 지점을 순차로만 처리(동시 로그인 금지)
        run(n, a.months, today, ym=ym)


if __name__ == "__main__":
    main()
