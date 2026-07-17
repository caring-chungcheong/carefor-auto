# -*- coding: utf-8 -*-
"""차량 정비이력 + 첨부 내역서(견적서·영수증) 수집 (읽기 전용).

케어포 2-4 차량관리 → 차량별 정비기록(정비일 범위 조회) → 각 행 [조회] 내역서를 직접 fetch
→ 첨부파일(/ct_att/car_maintenance_history/...)을 그대로 다운로드.

실행: py -X utf8 -m audit.collect_car_maintenance [지점키=청주] [--from 2024.08.01]
결과: audit_results/정비이력_<지점>/<차량명>/ 아래 첨부파일 + index.json

⚠️ 탐색으로 확인된 사실(2026-07-17):
  · 정비기록 그리드는 g-t > g-td 를 5칸(연번·정비일·정비구분·정비내역·조회)씩 끊어야 행이 된다
    (g-b 는 행 단위가 아니라 전체 묶음 1개).
  · 정비일 범위를 채우고 '조회'를 눌러야 기록이 나온다(비우면 "조회된 정비기록이 없습니다").
  · 로딩 마스크(#mask_div)가 클릭을 가로채므로 JS click 사용.
  · 수리비·타이어 사이즈는 케어포 필드에 없다 — 첨부 PDF(정비 내역서) 안에 있다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from src import credentials
from src.config import Config, config_path
from src.carefor_client import extract_g_pammgno, build_spa_hash, _navigate_spa
from audit.collector import PORTAL_URL, DN_BASE

sys.stdout.reconfigure(encoding="utf-8")
RES = Path(__file__).resolve().parent.parent / "audit_results"
SAFE = re.compile(r'[\\/:*?"<>|]')

ROWS_JS = r"""
() => {
  const t = Array.from(document.querySelectorAll('g-t'))
    .find(x => /정비구분/.test(x.textContent) && /정비내역/.test(x.textContent));
  if (!t) return [];
  const tds = Array.from(t.querySelectorAll('g-td'));
  const out = [];
  for (let i = 0; i + 4 < tds.length + 1; i += 5) {
    const g = tds.slice(i, i + 5);
    const c = g.map(x => x.textContent.trim().replace(/\s+/g, ' '));
    if (!/^\d+$/.test(c[0])) continue;
    const sp = g[4].querySelector('span[param-info]');
    out.push({no: c[0], date: c[1], kind: c[2], desc: c[3],
              param: sp ? sp.getAttribute('param-info') : '',
              view:  sp ? sp.getAttribute('page-info') : ''});
  }
  return out;
}
"""

FETCH_JS = r"""
async ([view, param]) => {
  const body = new URLSearchParams();
  try { const o = JSON.parse(param.replace(/'/g, '"')); for (const k in o) body.append(k, o[k]); }
  catch (e) { return ''; }
  const r = await fetch('/layer/modal/' + view + '.php',
    {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body});
  return await r.text();
}
"""

FILL_JS = r"""
([s, e]) => {
  const m = document.getElementById('mask_div'); if (m) m.style.display = 'none';
  let sec = null;
  document.querySelectorAll('div,section,form').forEach(d => {
    const t = d.textContent || '';
    if (!sec && t.includes('정비구분') && t.includes('정비내역')
        && d.querySelectorAll('input').length >= 2 && d.querySelectorAll('input').length <= 6) sec = d;
  });
  if (!sec) return false;
  const ins = Array.from(sec.querySelectorAll('input')).filter(i => i.getBoundingClientRect().width > 0);
  if (ins.length < 2) return false;
  ins[0].value = s; ins[0].dispatchEvent(new Event('change', {bubbles: true}));
  ins[1].value = e; ins[1].dispatchEvent(new Event('change', {bubbles: true}));
  const b = Array.from(sec.querySelectorAll('button,a,span,div,input[type=button]'))
    .find(x => (x.textContent || x.value || '').trim() === '조회');
  if (b) b.click();
  return true;
}
"""


def _login(p, ctmnumb: str):
    pid, ppw = credentials.get_portal_credentials()
    br = p.chromium.launch(headless=True)
    ctx = br.new_context(http_credentials={"username": pid, "password": ppw})
    pg = ctx.new_page()
    pg.goto(PORTAL_URL, wait_until="domcontentloaded")
    pg.wait_for_function("typeof login2 === 'function'", timeout=15000)
    with ctx.expect_page(timeout=60000) as npi:
        pg.evaluate(f"login2('{ctmnumb}')")
    page = npi.value
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    page.wait_for_load_state("networkidle", timeout=30000)
    return br, page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("branch", nargs="?", default="청주")
    ap.add_argument("--from", dest="dfrom", default="2024.08.01", help="정비일 시작 (개소일 권장)")
    ap.add_argument("--to", dest="dto", default=time.strftime("%Y.%m.%d"))
    args = ap.parse_args()

    cfg = Config.load(config_path())
    b = next(x for x in cfg.branches if args.branch in x.name)
    outdir = RES / f"정비이력_{b.name}"
    outdir.mkdir(parents=True, exist_ok=True)

    index, t0, n_file = [], time.time(), 0
    with sync_playwright() as p:
        br, page = _login(p, b.ctmnumb)
        g = extract_g_pammgno(page)
        _navigate_spa(page, f"{DN_BASE}#" + build_spa_hash(
            "left_sub2", "/transport/view.transport_car_manage", "2-4.차량관리", g))
        page.wait_for_timeout(2500)
        page.evaluate("() => { const m=document.getElementById('mask_div'); if(m) m.style.display='none'; }")

        # 차량번호·연식은 타이어 사이즈 마스터(차량별 1회 조사)에 필요해 함께 수집
        cars = page.evaluate("""() => Array.from(document.querySelectorAll('g-tf[data-key]')).map(e=>{
            let n='', k='', num='', md='', st='';
            try{ const j=JSON.parse(e.getAttribute('data-info').replace(/&quot;/g,'"'));
              n=j.carname; k=j.carkind; num=j.carnumb; md=j.carmodl; st=j.carstdt; }catch(_){}
            return {key:e.getAttribute('data-key'), name:n, kind:k, numb:num, modl:md, stdt:st}; })""")
        print(f"{b.name} — 차량 {len(cars)}대 · 정비일 {args.dfrom}~{args.dto}", flush=True)

        for c in cars:
            page.evaluate("""(k)=>{ const m=document.getElementById('mask_div'); if(m) m.style.display='none';
              const el=Array.from(document.querySelectorAll('g-tf[data-key]')).find(e=>e.getAttribute('data-key')===k);
              if(el) el.click(); }""", c["key"])
            page.wait_for_timeout(1500)
            page.evaluate("""()=>{ const el=Array.from(document.querySelectorAll('li,a,button,span,td,th'))
              .find(e=>(e.textContent||'').trim().startsWith('정비기록')); if(el) el.click(); }""")
            page.wait_for_timeout(1200)
            page.evaluate(FILL_JS, [args.dfrom, args.dto])
            page.wait_for_timeout(2200)

            rows = page.evaluate(ROWS_JS)
            cdir = outdir / SAFE.sub("_", c["name"])
            for r in rows:
                mv = re.search(r"'view'\s*:\s*'([^']+)'", r["view"] or "")
                html = page.evaluate(FETCH_JS, [mv.group(1), r["param"]]) if (mv and r["param"]) else ""
                # ★ 첨부는 2종이고 **호스트·경로가 다르다** (2026-07-17 실측):
                #   · PDF  : dn.carefor.co.kr  /ct_att/car_maintenance_history/... 
                #            <a href="/ct_att/..." download="원본파일명">  (상대경로 + download 속성)
                #   · 이미지: image.carefor.co.kr /ct_img/car_maintenance_history/...
                #            <script> photo_items[..].push({ src:'https://image.carefor.co.kr/ct_img/...jpg', w,h })
                #            → a 태그도 download 속성도 **없다**. 인라인 <img> 는 300x424 썸네일이라 못 쓴다.
                #              src 의 원본은 2480x3507 로 판독 가능.
                # 예전엔 /ct_att/ + download 패턴만 봐서 **이미지 첨부를 전부 놓쳤고**,
                # 그 탓에 "서구는 첨부를 안 올린다(11%)"고 잘못 결론냈다(실제로는 JPG 로 올리고 있었다).
                atts = [(DN_BASE.rstrip("/") + u, n) for u, n in
                        re.findall(r'href="(/ct_att/[^"]+)"\s+download="([^"]+)"', html or "")]
                img_urls = re.findall(r"src\s*:\s*'(https?://[^']+/ct_img/[^']+)'", html or "")
                img_names = re.findall(r"data-kind='img'[^>]*data-name=\"([^\"]+)\"", html or "")
                for i, u in enumerate(dict.fromkeys(img_urls)):
                    atts.append((u, img_names[i] if i < len(img_names) else u.rsplit("/", 1)[-1]))
                saved = []
                for url, fname in atts:
                    cdir.mkdir(parents=True, exist_ok=True)
                    safe = SAFE.sub("_", fname)
                    fp = cdir / safe
                    try:
                        buf = page.request.get(url)   # url 은 이미 절대경로(PDF=dn, 이미지=image 호스트)
                        fp.write_bytes(buf.body())
                        saved.append(safe)
                        n_file += 1
                    except Exception as e:
                        print(f"    첨부 실패 {fname}: {e}", flush=True)
                index.append({"car": c["name"], "kind": c["kind"],
                              "numb": c.get("numb", ""), "modl": c.get("modl", ""), "date": r["date"],
                              "type": r["kind"], "desc": r["desc"],
                              "cmhmgno": (re.search(r"'cmhmgno'\s*:\s*'(\d+)'", r["param"]) or [None, ""])[1],
                              "files": saved})
            n_att = sum(1 for x in index if x["car"] == c["name"] and x["files"])
            print(f"  {c['name']:<14} 정비 {len(rows):>3}건 · 첨부보유 {n_att:>2}건", flush=True)
        br.close()

    (outdir / "index.json").write_text(
        json.dumps({"branch": b.name, "from": args.dfrom, "to": args.dto,
                    "cars": [{k: c.get(k, "") for k in ("name", "kind", "numb", "modl", "stdt")} for c in cars],
                    "records": index},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {outdir} (정비 {len(index)}건, 첨부파일 {n_file}개, {time.time()-t0:.0f}초)", flush=True)


if __name__ == "__main__":
    main()
