# -*- coding: utf-8 -*-
"""3-2 상태변화 기록(항목 34④) 수집·주별 집계 단독 테스트."""
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

from src.config import Config, config_path
from src.carefor_client import extract_g_pammgno
from .explore_pages import login
from .branch_pages import _goto, CLOSE_MODAL_JS, GET_TEXT_JS, parse_status
from .items import BRANCH_CUTOFFS


def main():
    branch = sys.argv[1] if len(sys.argv) > 1 else "천안점"
    cfg = Config.load(config_path())
    b = next(x for x in cfg.branches if branch in x.name)
    cutoff = next((v for k, v in BRANCH_CUTOFFS.items() if branch in k or k in b.name), "2024.01.01")
    sm = max(cutoff.replace(".", "")[:6], "202401")
    y, m = int(sm[:4]), int(sm[4:6])
    weeks = []
    with sync_playwright() as p:
        browser, page = login(p, b.ctmnumb)
        g = extract_g_pammgno(page)
        _goto(page, "status", g)
        page.evaluate(CLOSE_MODAL_JS)
        today = date.today()
        while (y, m) <= (today.year, today.month):
            page.evaluate(f"reloadPage({{'yyyymm':'{y}{m:02d}'}})")
            page.wait_for_timeout(2000)
            ws = parse_status(page.evaluate(GET_TEXT_JS), f"{y}-{m:02d}")
            weeks += ws
            m += 1
            if m > 12:
                y, m = y + 1, 1
        browser.close()
    done_w = [w for w in weeks if w["end"] < date.today()]
    miss = [w for w in done_w if w["total"] and w["done"] < w["total"]]
    print(f"{branch}: 총 {len(weeks)}주 수집, 완료 주 {len(done_w)}, 미달 주 {len(miss)}")
    for w in miss[:12]:
        print(f"    {w['start']}~{w['end']}: {w['done']}/{w['total']}")


if __name__ == "__main__":
    main()
