# 항목33 소스 탐색: 3-1-4 식사만족도조사 + 6-1 주간식단표 구조 덤프 (읽기 전용)
import sys, io, os, json
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
from src.config import Config, config_path
from src.carefor_client import build_spa_hash, _navigate_spa, extract_g_pammgno
from audit.explore_pages import login
from audit.branch_pages import CLOSE_MODAL_JS

OUTDIR = "audit_results/explore"

DUMP = r"""
(() => {
  const out = {};
  const sels = {};
  document.querySelectorAll('select').forEach(s => {
    const p = (s.name||'').replace(/\[\d+\]/g,'[]').slice(0,24);
    sels[p] = (sels[p]||0)+1;
  });
  out.select_prefixes = sels;
  const inps = {};
  document.querySelectorAll('input').forEach(s => {
    const p = (s.name||s.id||s.type||'').replace(/\[\d+\]/g,'[]').slice(0,24);
    inps[p] = (inps[p]||0)+1;
  });
  out.input_names = inps;
  out.total_selects = document.querySelectorAll('select').length;
  out.total_inputs = document.querySelectorAll('input').length;
  out.tables = document.querySelectorAll('table').length;
  out.trs = document.querySelectorAll('tr').length;
  out.buttons = [...document.querySelectorAll('button,a.btn,input[type=button]')].map(b=>(b.innerText||b.value||'').trim()).filter(Boolean).slice(0,25);
  out.fns = {};
  const cand=['reloadPage','fn_search','doSearch','search','moveTo','goPage','fn_list','list_reload','weekly_menu_reload','satisfaction_reload','load_contents_form','datepicker'];
  for (const f of cand) out.fns[f]=typeof window[f];
  const root = document.querySelector('#r_padding') || document.querySelector('#contents') || document.body;
  out.text = (root.innerText||'').replace(/\s+/g,' ').slice(0,1200);
  // 첫 두 테이블 헤더행 텍스트
  out.table_heads = [...document.querySelectorAll('table')].slice(0,3).map(t=>{
    const tr = t.querySelector('tr');
    return tr ? (tr.innerText||'').replace(/\s+/g,' ').slice(0,200) : '';
  });
  return out;
})()
"""

def dump(page, label, save_html=None):
    try:
        d = page.evaluate(DUMP)
    except Exception as e:
        print(f"[{label}] evaluate 오류: {e}"); return
    print(f"\n===== {label} =====")
    print(" url:", page.url[:100])
    for k in ("total_selects","total_inputs","tables","trs"):
        print(f" {k}: {d[k]}")
    print(" select_prefixes:", d["select_prefixes"])
    print(" input_names:", d["input_names"])
    print(" buttons:", d["buttons"])
    print(" fns:", {k:v for k,v in d["fns"].items() if v!='undefined'})
    print(" table_heads:", d["table_heads"])
    print(" text:", d["text"])
    if save_html:
        try:
            html = page.content()
            os.makedirs(OUTDIR, exist_ok=True)
            p = os.path.join(OUTDIR, save_html)
            io.open(p, "w", encoding="utf-8").write(html)
            print(f" [저장] {p} ({len(html)}자)")
        except Exception as e:
            print(" html 저장 오류:", e)

def go(page, typ, view, title, g):
    h = build_spa_hash(typ, view, title, g)
    _navigate_spa(page, f"https://dn.carefor.co.kr/#{h}")
    page.wait_for_timeout(5000)
    try: page.evaluate(CLOSE_MODAL_JS)
    except Exception: pass
    page.wait_for_timeout(1200)

def main():
    key = sys.argv[1] if len(sys.argv) > 1 else "청주"
    cfg = Config.load(config_path())
    b = next(x for x in cfg.branches if key in x.name)
    with sync_playwright() as pw:
        browser, page = login(pw, b.ctmnumb)
        g = extract_g_pammgno(page)
        print("g_pammgno:", g)
        # 3-1-4 식사(간식) 만족도 조사 및 반영
        go(page, "left_sub3", "/share/care/view.meal_satisfaction_daynurse", "3-1-4.식사(간식) 만족도 조사 및 반영", g)
        dump(page, "3-1-4 식사만족도조사", save_html="live_3-1-4.html")
        # 6-1 주간식단표
        go(page, "left_sub6", "/share/safe/view.weekly_menu", "6-1.주간식단표", g)
        dump(page, "6-1 주간식단표", save_html="live_6-1.html")
        browser.close()

if __name__ == "__main__":
    main()
