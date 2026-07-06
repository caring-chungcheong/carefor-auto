# -*- coding: utf-8 -*-
"""1-6 수급자 안전관리 설명(항목 19④) 수집·파싱 단독 테스트."""
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

from src.config import Config, config_path
from src.carefor_client import extract_g_pammgno
from .explore_pages import login
from .branch_pages import _goto, CLOSE_MODAL_JS, SAFE_TAB_JS, parse_safe


def main():
    branch = sys.argv[1] if len(sys.argv) > 1 else "천안점"
    cfg = Config.load(config_path())
    b = next(x for x in cfg.branches if branch in x.name)
    with sync_playwright() as p:
        browser, page = login(p, b.ctmnumb)
        g = extract_g_pammgno(page)
        _goto(page, "guide", g)
        for y in range(2024, date.today().year + 1):
            page.evaluate(f"reloadPage({{'yy':'{y}'}})")
            txt = ""
            for _ in range(8):
                page.wait_for_timeout(800)
                page.evaluate(CLOSE_MODAL_JS)
                txt = page.evaluate(SAFE_TAB_JS)
                if "총인원" in txt:
                    break
            s = parse_safe(txt)
            print(f"{y}: 총 {s['total']} / 설명 {s['done']} / 미설명 {s['undone']} · 기록 {len(s['rows'])}건"
                  + (f" (첫 기록 {s['rows'][-1]['date']} ~ 최근 {s['rows'][0]['date']})" if s["rows"] else ""))
        browser.close()


if __name__ == "__main__":
    main()
