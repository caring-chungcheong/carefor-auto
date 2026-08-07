# -*- coding: utf-8 -*-
"""수기 점수표 생성 — 자동 판정과 **같은 36항목·같은 배점**으로 사람이 직접 점수를 매기는 화면.

왜 생성기인가: 항목·배점을 HTML 에 손으로 박으면 items.py 가 바뀔 때 조용히 어긋난다.
평가 매뉴얼(items.py)을 읽어 만들어 두 화면의 기준이 갈리지 않게 한다.

저장: 브라우저 localStorage(지점별). 서버에 안 보내므로 **점수는 이 브라우저에만** 남는다.
      공유가 필요하면 CSV 내려받기로 주고받는다.

실행: py -X utf8 -m audit.build_manual_score
결과: docs/manual_score.html  (공유허브 ?page=manualscore / 관제탑에서 연다)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "manual_score.html"
BRANCHES = ["둔산점", "서구점", "천안점", "청주 오창점"]


def build() -> str:
    from audit.items import ITEMS

    data = [{"no": it["no"], "name": it["name"], "method": it.get("method", ""),
             "loc": it.get("loc", ""), "total": it.get("total", 0),
             "criteria": it.get("criteria", ""),
             "auto_subs": it.get("auto_subs", []),
             "subs": [{"label": s["label"], "score": s["score"],
                       "steps": s["steps"], "text": s["text"]} for s in it.get("subs", [])]}
            for it in ITEMS]
    total = sum(i["total"] for i in data)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!doctype html><html lang="ko"><meta charset="utf-8">
<title>수기 점수표 — 지점점검</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{color-scheme:light dark}}
*{{box-sizing:border-box}}
body{{font:14px/1.55 'Pretendard Variable',Pretendard,'Malgun Gothic',sans-serif;
margin:0;padding:16px;background:#f6f7f8;color:#1a1a1a}}
h1{{font-size:19px;margin:0 0 3px}}
.sub{{color:#666;font-size:12px;margin-bottom:12px}}
.bar{{position:sticky;top:0;z-index:20;background:#2f5c64;color:#fff;border-radius:10px;
padding:10px 14px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:14px}}
.bar select,.bar button{{font:600 13px inherit;border-radius:6px;border:0;padding:6px 11px;cursor:pointer}}
.bar select{{background:#fff;color:#1a1a1a}}
.bar button{{background:#5f9ea8;color:#fff}}
.bar button:hover{{background:#7cbcc6}}
.score{{margin-left:auto;font-weight:800;font-size:16px}}
.score small{{font-weight:400;opacity:.8;font-size:12px}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e3e5e8;border-radius:10px;overflow:hidden}}
th,td{{padding:7px 9px;border-bottom:1px solid #eef0f1;text-align:left;vertical-align:top;font-size:13px}}
th{{background:#eef2f3;font-size:12px;position:sticky;top:52px;z-index:10}}
tr.item td{{background:#fafbfb;font-weight:700}}
td.no{{width:38px;color:#888;font-weight:600}}
td.pt{{width:64px;text-align:right;white-space:nowrap}}
.tag{{font-size:10px;border-radius:4px;padding:1px 5px;margin-left:5px;font-weight:600}}
.auto{{background:#e5f0e8;color:#2b6b3f}} .man{{background:#fdeee0;color:#9a5b12}}
.opt{{display:inline-flex;gap:4px;flex-wrap:wrap}}
.opt label{{border:1px solid #d7dadd;border-radius:6px;padding:2px 9px;cursor:pointer;font-size:12px;background:#fff}}
.opt input{{display:none}}
.opt input:checked+span{{font-weight:800}}
.opt label:has(input:checked){{background:#2f5c64;color:#fff;border-color:#2f5c64}}
.memo{{width:100%;border:1px solid #dfe2e4;border-radius:6px;padding:4px 7px;font:12px inherit;background:#fff}}
details.cri{{margin-top:3px}} details.cri summary{{font-size:11px;color:#7a8288;cursor:pointer}}
details.cri div{{font-size:11px;color:#666;line-height:1.5;margin-top:3px;white-space:normal}}
.warn{{background:#fff4e5;border:1px solid #f0c992;border-radius:8px;padding:9px 12px;
font-size:12px;color:#7a4a00;margin-bottom:12px}}
@media(prefers-color-scheme:dark){{
body{{background:#16181a;color:#e6e6e6}} table{{background:#1e2124;border-color:#2e3236}}
th{{background:#24282b}} tr.item td{{background:#212528}} td,th{{border-color:#2a2d30}}
.opt label,.memo{{background:#1a1d20;border-color:#3a3f44;color:#e6e6e6}}
.warn{{background:#2e2415;border-color:#5a4523;color:#e0b877}} }}
/* 인쇄: 조작용 UI(버튼·안내)는 빼고 지점·합계·점수·메모만 남긴다.
   항목이 쪽 경계에서 잘리면 채점표로 못 쓰므로 세부행 단위로 안 쪼갠다. */
@media print{{
  body{{padding:0;background:#fff}}
  .bar{{position:static;background:#fff;color:#000;padding:0 0 6px;border-bottom:2px solid #000;
  border-radius:0;margin-bottom:8px}}
  .bar button{{display:none}}
  .bar select{{border:0;background:transparent;font-weight:800;font-size:15px;padding:0;
  appearance:none;-webkit-appearance:none}}
  .score{{color:#000}}
  .warn{{display:none}}
  details.cri{{display:none}}
  th{{position:static;background:#eee !important;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
  table{{border-radius:0}}
  tr{{break-inside:avoid}}
  .opt label{{border-color:#999}}
  .opt label:has(input:checked){{background:#000 !important;color:#fff !important;
  -webkit-print-color-adjust:exact;print-color-adjust:exact}}
  .memo{{border:0;border-bottom:1px solid #bbb;border-radius:0}}
  .memo::placeholder{{color:transparent}}
}}
</style>
<h1>✍️ 수기 점수표 — 지점점검</h1>
<div class="sub">자동 판정과 같은 36항목 · 총 {total:g}점 · items.py 기준 {now} 생성</div>
<div class="warn">💾 점수는 <b>이 브라우저에만</b> 저장됩니다(서버 전송 없음). 다른 PC와 나누려면 <b>CSV 내려받기</b>를 쓰세요.</div>

<div class="bar">
  <select id="br"></select>
  <button onclick="csv()">📥 CSV 내려받기</button>
  <button onclick="print()">🖨️ 인쇄</button>
  <button onclick="clr()">↺ 이 지점 초기화</button>
  <span class="score">합계 <b id="sum">0</b><small> / {total:g}점</small></span>
</div>
<table id="t"><thead><tr>
<th class="no">번호</th><th>항목 · 세부</th><th class="pt">배점</th><th style="width:210px">점수</th><th style="width:22%">메모</th>
</tr></thead><tbody id="tb"></tbody></table>

<script>
const ITEMS = {json.dumps(data, ensure_ascii=False)};
const BRANCHES = {json.dumps(BRANCHES, ensure_ascii=False)};
const key = () => 'manualscore-' + br.value;
let state = {{}};

const br = document.getElementById('br');
br.innerHTML = BRANCHES.map(b => `<option>${{b}}</option>`).join('');

function load() {{
  try {{ state = JSON.parse(localStorage.getItem(key()) || '{{}}'); }} catch (e) {{ state = {{}}; }}
  render();
}}
function save() {{
  try {{ localStorage.setItem(key(), JSON.stringify(state)); }} catch (e) {{}}
  total();
}}
function total() {{
  let s = 0;
  ITEMS.forEach(it => it.subs.forEach(sb => {{
    const v = state[it.no + sb.label];
    if (v && v.p !== '' && v.p != null) s += Number(v.p);
  }}));
  document.getElementById('sum').textContent = Math.round(s * 100) / 100;
}}
function render() {{
  const rows = [];
  ITEMS.forEach(it => {{
    const tag = it.method === 'auto'
      ? '<span class="tag auto">자동</span>' : '<span class="tag man">수기</span>';
    rows.push(`<tr class="item"><td class="no">${{it.no}}</td>`
      + `<td colspan="4">${{esc(it.name)}}${{tag}}`
      + `<span style="font-weight:400;color:#8a9096;font-size:11px"> · ${{esc(it.loc)}} · ${{it.total}}점</span>`
      + `<details class="cri"><summary>판정기준 펼치기</summary><div>${{esc(it.criteria)}}</div></details></td></tr>`);
    it.subs.forEach(sb => {{
      const k = it.no + sb.label;
      const cur = state[k] || {{}};
      const opts = sb.steps.map(v =>
        `<label><input type="radio" name="r${{k}}" value="${{v}}"`
        + `${{String(cur.p) === String(v) ? ' checked' : ''}} onchange="pick('${{k}}',this.value)">`
        + `<span>${{v}}</span></label>`).join('')
        + `<label><input type="radio" name="r${{k}}" value=""`
        + `${{cur.p == null || cur.p === '' ? ' checked' : ''}} onchange="pick('${{k}}','')">`
        + `<span>미평가</span></label>`;
      rows.push(`<tr><td class="no"></td><td>${{sb.label}} ${{esc(sb.text)}}</td>`
        + `<td class="pt">${{sb.score}}</td><td><div class="opt">${{opts}}</div></td>`
        + `<td><input class="memo" value="${{esc(cur.m || '')}}" `
        + `oninput="memo('${{k}}',this.value)" placeholder="근거·비고"></td></tr>`);
    }});
  }});
  document.getElementById('tb').innerHTML = rows.join('');
  total();
}}
function pick(k, v) {{ (state[k] = state[k] || {{}}).p = v; save(); }}
function memo(k, v) {{ (state[k] = state[k] || {{}}).m = v; save(); }}
function clr() {{
  if (!confirm(br.value + ' 점수를 모두 지울까요?')) return;
  state = {{}}; localStorage.removeItem(key()); render();
}}
function esc(s) {{ return String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }}
function csv() {{
  const L = [['지점', '번호', '항목', '세부', '내용', '배점', '점수', '메모']];
  ITEMS.forEach(it => it.subs.forEach(sb => {{
    const c = state[it.no + sb.label] || {{}};
    L.push([br.value, it.no, it.name, sb.label, sb.text, sb.score,
            c.p == null || c.p === '' ? '' : c.p, c.m || '']);
  }}));
  const body = L.map(r => r.map(x => `"${{String(x).replace(/"/g, '""')}}"`).join(',')).join('\\r\\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['\\ufeff' + body], {{type: 'text/csv;charset=utf-8'}}));
  a.download = `수기점수_${{br.value}}_${{new Date().toISOString().slice(0, 10)}}.csv`;
  a.click();
}}
br.onchange = load;
load();
</script>
</html>"""


def main() -> int:
    OUT.write_text(build(), encoding="utf-8")
    print("생성:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
