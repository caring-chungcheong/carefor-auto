# -*- coding: utf-8 -*-
"""1-6 직원인권 보호지침 탭 구조 탐색."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

from src.config import Config, config_path
from src.carefor_client import extract_g_pammgno
from .explore_pages import login, OUT_DIR, PAGES


def main():
    branch = sys.argv[1] if len(sys.argv) > 1 else "천안점"
    cfg = Config.load(config_path())
    b = next(x for x in cfg.branches if branch in x.name)

    with sync_playwright() as p:
        browser, page = login(p, b.ctmnumb)
        g = extract_g_pammgno(page)

        from src.carefor_client import build_spa_hash, _navigate_spa
        type_, view, title = PAGES["1-6"]
        _navigate_spa(page, f"https://dn.carefor.co.kr/#{build_spa_hash(type_, view, title, g)}")
        page.wait_for_timeout(3500)

        # 알림사항 모달 닫기 (mask_div가 클릭을 가로챔)
        page.evaluate(
            """
            (() => {
              const btn = Array.from(document.querySelectorAll('div.m_button, .m_button'))
                .find(el => el.textContent.trim() === '창닫기');
              if (btn) btn.click();
              const mask = document.getElementById('mask_div');
              if (mask) mask.style.display = 'none';
            })()
            """
        )
        page.wait_for_timeout(1000)

        # 3번 탭 클릭: 직원인권 보호지침(연1회) — 실제 마우스 클릭
        page.click(".tabmenu2 li:has-text('직원인권')")
        page.wait_for_timeout(5000)

        # 모든 탭 타깃 div 크기 확인
        sizes = page.evaluate(
            """
            (() => {
              const out = {};
              ['div_safe','div_transport','tab_div_guide_offer_when_join','tab_div_patient_yearly_management'].forEach(id => {
                const el = document.getElementById(id);
                out[id] = el ? (el.innerText || '').length : -1;
              });
              return out;
            })()
            """
        )
        print("탭 div 크기:", sizes)

        txt = page.evaluate(
            "(() => { const el = document.querySelector('#tab_div_guide_offer_when_join'); return el ? el.innerText : 'TARGET NOT FOUND'; })()"
        )
        html = page.evaluate(
            "(() => { const el = document.querySelector('#tab_div_guide_offer_when_join'); return el ? el.innerHTML : ''; })()"
        )
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "tab_16_rights.txt").write_text(txt, encoding="utf-8")
        (OUT_DIR / "tab_16_rights.html").write_text(html, encoding="utf-8")
        print(f"텍스트 {len(txt)}자, HTML {len(html)}자 저장")
        print("--- 앞부분 ---")
        print(txt[:1500])
        browser.close()


if __name__ == "__main__":
    main()
