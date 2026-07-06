# -*- coding: utf-8 -*-
"""1-10 연계기록지(항목 30②) 수집·파싱 단독 테스트."""
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

from src.config import Config, config_path
from src.carefor_client import extract_g_pammgno
from .explore_pages import login
from .branch_pages import _goto, CLOSE_MODAL_JS, GET_TEXT_JS, parse_connect
from .items import BRANCH_CUTOFFS


def main():
    branch = sys.argv[1] if len(sys.argv) > 1 else "천안점"
    cfg = Config.load(config_path())
    b = next(x for x in cfg.branches if branch in x.name)
    cutoff = next((v for k, v in BRANCH_CUTOFFS.items() if branch in k or k in b.name), "2024.01.01")
    with sync_playwright() as p:
        browser, page = login(p, b.ctmnumb)
        g = extract_g_pammgno(page)
        _goto(page, "connect", g)
        page.evaluate(CLOSE_MODAL_JS)
        s0 = max(cutoff.replace(".", ""), "20240101")
        e0 = date.today().strftime("%Y%m%d")
        page.evaluate(f"document.querySelector('#id_s_date').value='{s0}';"
                      f"document.querySelector('#id_e_date').value='{e0}';"
                      "load_contents_form('ptcSendReport')")
        page.wait_for_timeout(2500)
        c = parse_connect(page.evaluate(GET_TEXT_JS))
        print(f"{branch} ({s0}~{e0}): 총 {c['total']}건 · 발송 {c['sent']} · 미발송 {c['unsent']} · 행 {len(c['rows'])}건")
        for r in c["rows"][:8]:
            late = " ⚠기한초과" if r["provided"] and r["leave"] and r["provided"] > r["leave"] else ""
            print(f"    {r['name']} 퇴소 {r['leave']}({r['reason']}) 작성 {r['written']} 제공 {r['provided']} {r['method']}{late}")
        browser.close()


if __name__ == "__main__":
    main()
