# 항목33 식사(간식)제공결과 수집기 — 시설 단위(3-1-4 만족도/반영 + 6-1 식단표), 읽기 전용
# ②만족도 반기별 / ③결과반영 월1회 / ⑤1식4찬 식단표 게시 자동판정
import sys, json, io, os, re, datetime
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
from src.config import Config, config_path
from src.carefor_client import build_spa_hash, _navigate_spa, extract_g_pammgno
from audit.explore_pages import login
from audit.branch_pages import CLOSE_MODAL_JS

# --- 3-1-4 식사만족도조사/결과반영 추출 (innerText 파싱) ---
SAT_JS = r"""
(() => {
  const root = document.querySelector('#r_padding') || document.body;
  const txt = (root.innerText || '').replace(/\r/g, '');
  const year = ((txt.match(/(20\d{2})년\s*식사\(간식\)\s*만족도/) || [])[1]) || '';
  const seg = (a, b) => {
    const i = txt.indexOf(a); if (i < 0) return '';
    const j = b ? txt.indexOf(b, i + a.length) : -1;
    return txt.slice(i, j < 0 ? txt.length : j);
  };
  const dateRe = /20\d{2}\.\d{2}\.\d{2}/g;
  const fh = (seg('상반기', '하반기').match(dateRe) || []);
  const sh = (seg('하반기', '신규등록').match(dateRe) || []);
  // 결과반영 월별
  const refl = seg('결과반영', '출력');
  const months = {};
  const mre = /(0[1-9]|1[0-2])월([\s\S]{0,40}?)(?=(0[1-9]|1[0-2])월|$)/g;
  let m;
  while ((m = mre.exec(refl))) {
    const s = m[2];
    months[m[1]] = s.includes('미작성') ? '미작성'
                 : s.includes('없습니다') ? '대상없음'
                 : /작성|반영/.test(s) ? '작성' : s.replace(/\s+/g,'').slice(0,8);
  }
  return { year, firstHalf: fh, secondHalf: sh, months };
})()
"""

# --- 6-1 주간식단표 추출: 게시 여부 + 점심 반찬 수(1식4찬) — g-td[data-gt-row]/menu_div 기반 ---
MENU_JS = r"""
(() => {
  const root = document.querySelector('#r_padding') || document.body;
  const txt = (root.innerText || '').replace(/\r/g, '');
  const period = ((txt.match(/20\d{2}\.\d{2}\.\d{2}\s*~\s*20\d{2}\.\d{2}\.\d{2}/) || [])[0]) || '';
  function mealMax(label) {
    // 라벨 셀(data-gt-col=0)의 row 인덱스 찾기
    let rowIdx = null;
    document.querySelectorAll('g-td[data-gt-col="0"]').forEach(c => {
      if ((c.innerText || '').replace(/\s/g, '').includes(label)) rowIdx = c.getAttribute('data-gt-row');
    });
    if (rowIdx === null) return 0;
    let best = 0;
    document.querySelectorAll('g-td[data-gt-row="' + rowIdx + '"]').forEach(c => {
      if (c.getAttribute('data-gt-col') === '0') return;
      const div = c.querySelector('.menu_div') || c;
      const lines = (div.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
      if (lines.length > best) best = lines.length;
    });
    return best;
  }
  return { period, hasMenu: /점심\s*식단/.test(txt), lunchDishes: mealMax('점심식단'), dinnerDishes: mealMax('저녁식단') };
})()
"""


def unfinished_targets(rows, half: str, year: int, bigo: str) -> tuple[list[str], int, int]:
    """반기 조사 대상자 목록 → 실제로 지적해야 할 미참여자.

    행 = [연번, 현황, 수급자명, 성별, 입소일, 작성일]. 케어포 '설문 미완료(78/80)' 팝업에서 온다.
    거르는 순서(평가기준 33② '모든 수급자', '신규는 입소 반기 제외'):
      1) 현황이 '수급중'이 아닌 사람(보류·퇴소)은 제외 — 분모에 섞여 들어온다.
      2) 그 반기에 입소한 신규는 제외 — 조사일에 아직 없던 사람이다.
      3) 작성일이 '미참여'인 사람만 남긴다.
      4) 조사 비고에 이름이 적혀 있으면 제외 — 지점이 '결석으로 26.01.14 직접 설문 진행함'
         식으로 사유를 남기면 그게 파악한 근거다(실측: 그렇게 적힌 사람은 참여 처리돼 있었다).
    반환: (지적대상 이름들, 수급중 미참여 수, 신규로 제외한 수)
    """
    lo, hi = ((f"{year}.01.01", f"{year}.06.30") if half == "1"
              else (f"{year}.07.01", f"{year}.12.31"))
    cur = [r for r in rows if len(r) >= 6 and r[1].strip() == "수급중" and r[5].strip() == "미참여"]
    newbie = [r for r in cur if lo <= r[4].strip() <= hi]
    target = [r for r in cur if not (lo <= r[4].strip() <= hi)]
    named = [r[2].strip() for r in target if r[2].strip() and r[2].strip() not in (bigo or "")]
    return named, len(cur), len(newbie)


def judge_item33(data, today):
    """②만족도 반기별 / ③결과반영 월1회 / ⑤1식4찬 식단표 자동판정. ①기피식품·④면담은 수기."""
    sat = data.get("satisfaction", {}); menu = data.get("menu", {})
    y, mth = today.year, today.month
    subs, notes = {}, []

    # ② 만족도 반기별 1회 (3-1-4 조사 기준). 없어도 미흡 단정 불가 — 면담·상담으로도 파악 가능 → '주의'(확인요망)
    fh = len(sat.get("firstHalf", [])); sh = len(sat.get("secondHalf", []))
    p2 = []
    if mth > 6 and fh == 0: p2.append(f"{y} 상반기")
    if mth == 12 and sh == 0: p2.append(f"{y} 하반기")
    notes.append(f"만족도조사 상반기 {fh}건·하반기 {sh}건" + (f" → {'·'.join(p2)} 상담/면담 확인요망" if p2 else ""))

    # ②-2 ★2026-07-28 케어포 개편으로 '설문 미완료(참여/전체)'와 미참여자 목록이 생겼다.
    #   기준이 '모든 수급자'라 조사 1건만으로 충족 처리하던 종전 판정은 빠진 사람을 못 잡았다.
    #   반기가 끝나기 전에는 지적하지 않는다(아직 채울 시간이 있다) — 진행현황만 알린다.
    #   ⚠️ 이름은 detail 에 넣지 않는다 — 대시보드(docs/dashboard_data.js)는 공개 저장소에 커밋된다.
    #      명단은 audit_results/(gitignore) 로만 나간다.
    unf = data.get("unfinished") or {}
    bigo = unf.get("bigo", "")
    for half, label, closed in (("1", "상반기", mth > 6), ("2", "하반기", mth == 12)):
        rows = unf.get(half) or []
        if not rows:
            continue
        named, n_cur, n_new = unfinished_targets(rows, half, y, bigo)
        base = (f"{label} 미참여 {n_cur}명(수급중)"
                + (f"·신규 {n_new}명 제외" if n_new else "")
                + f" → 비고 미기재 {len(named)}명")
        if named and closed:
            p2.append(f"{y} {label} 미참여 {len(named)}명")
            notes.append(base + " (반기 종료 — 비고에 사유 기재 또는 면담 확인요망)")
        else:
            notes.append(base + ("" if not named else " (반기 진행 중 — 연말까지 채우면 됨)"))

    subs["②"] = "주의" if p2 else "양호"

    # ③ 결과반영 월1회. 3-1-4 결과반영 칸이 비어도 실무상 상담일지(1-4)+요양기록지(3-1)에 매달 작성하므로
    #    자동 미흡 아님 → '주의'(상담일지+요양기록지 확인요망). (사용자 확정 2026-07: 통상 1~5월 상담일지+요양기록지 작성)
    months = sat.get("months", {})
    p3 = [f"{m:02d}월" for m in range(1, mth) if months.get(f"{m:02d}") == "미작성"]
    subs["③"] = "주의" if p3 else "양호"
    if p3: notes.append("결과반영 3-1-4 미기재 " + "·".join(p3) + " → 상담일지+요양기록지 확인요망")

    # ⑤ 1식4찬 식단표 게시 (점심 밥+국+4찬 = 5개 이상), 6-1에서 확인.
    #    점심 0찬 = 이번주 미입력 표본일 가능성 → 미흡 아니라 '주의'(확인요망). 입력됐는데 4찬 미만만 미흡.
    lunch = menu.get("lunchDishes", 0)
    if lunch >= 5:
        subs["⑤"] = "양호"; notes.append(f"식단표 게시 O(점심 {lunch}찬)")
    elif lunch == 0:
        subs["⑤"] = "주의"; notes.append("식단표 이번주 미입력(표본) — 게시 확인요망")
    else:
        subs["⑤"] = "미흡"; notes.append(f"식단표 점심 {lunch}찬(1식4찬 미달)")

    bad = [k for k, v in subs.items() if v == "미흡"]
    warn = [k for k, v in subs.items() if v == "주의"]
    status = "미흡" if bad else ("주의" if warn else "양호")
    detail = ("[자동: ②만족도조사·⑤식단표1식4찬 / ③결과반영은 3-1-4 미기재 시 상담일지+요양기록지 확인요망 / ①기피식품·④면담 수기] "
              + " · ".join(notes))
    return {"status": status, "sub_status": subs, "detail": detail}

def go(page, typ, view, title, g, marker=None):
    """페이지 이동 후 마커 텍스트가 실제로 뜰 때까지 폴링 — 고정대기보다 조기수집에 안전(클라우드 대비)."""
    h = build_spa_hash(typ, view, title, g)
    _navigate_spa(page, f"https://dn.carefor.co.kr/#{h}")
    page.wait_for_timeout(1500)
    try: page.evaluate(CLOSE_MODAL_JS)
    except Exception: pass
    if marker:
        try:
            page.wait_for_function(
                "m => ((document.querySelector('#r_padding')||document.body).innerText||'').includes(m)",
                arg=marker, timeout=9000)
        except Exception:
            page.wait_for_timeout(3000)  # 마커 안 뜨면 여유 대기 후 진행
    page.wait_for_timeout(1200)

# 팝업(#layerModal) 안 셀 읽기 / 닫기 — 미참여 목록·조사 비고 둘 다 이 레이어로 열린다
_LAYER_CELLS = ("() => { const m = document.querySelector('#layerModal'); if (!m) return null;"
                " return {text: (m.innerText||''),"
                " cells: [...m.querySelectorAll('g-td,td')].map(x => x.innerText.trim())}; }")
_LAYER_CLOSE = ("() => { const b = [...document.querySelectorAll('div,button,a,span')]"
                ".find(e => (e.textContent||'').trim() === '창닫기'); if (b) b.click();"
                " document.querySelectorAll('#layerModal,#mask_div').forEach(e => e.remove()); }")


def _open_layer(page, selector, tries: int = 3):
    """★evaluate 로 el.click() 하면 그리드 정렬 핸들러가 이벤트 없이 돌다 죽는다
    (gridTable.js setGridTableSorting → null.matches). 반드시 실제 마우스 클릭으로 연다.

    ★빈 결과를 그냥 돌려주지 말 것 — 첫 클릭이 그리드 로딩 전에 나가면 목록이 비어 오고,
      그러면 '미참여자 없음'으로 읽혀 **지적할 사람을 놓친 채 양호로 뜬다**(실측 2026-07-29 상반기).
      셀이 채워질 때까지 재시도하고, 그래도 비면 None(=수집 실패)로 알린다."""
    for attempt in range(tries):
        loc = page.locator(selector).first
        try:
            if not loc.count():
                page.wait_for_timeout(1500)
                continue
            loc.click()
        except Exception:
            page.wait_for_timeout(1500)
            continue
        for _ in range(12):                      # 레이어에 셀이 실제로 들어올 때까지
            page.wait_for_timeout(600)
            d = page.evaluate(_LAYER_CELLS)
            if d and d.get("cells"):
                try: page.evaluate(_LAYER_CLOSE)
                except Exception: pass
                page.wait_for_timeout(700)
                return d
        try: page.evaluate(_LAYER_CLOSE)
        except Exception: pass
        page.wait_for_timeout(1200)
    return None


def collect_unfinished(page):
    """3-1-4 반기별 '설문 미완료(n/m)' 팝업 + 조사별 '조회' 팝업의 비고.
    반환: {"1": [[연번,현황,이름,성별,입소일,작성일], ...], "2": [...], "bigo": "합친 비고"}
    수집 실패한 반기는 키를 아예 안 넣는다 — 빈 목록('미참여 0명')과 구분해야 판정이 거짓양호로 안 간다."""
    out = {"bigo": ""}
    # ★케어포 공지 팝업(#layerModal)이 화면을 덮고 있으면 첫 클릭이 막힌다 — 실측: 그 바람에
    #   상반기만 수집에 실패하고 하반기는 성공했다(공지를 치우는 사이 시간이 지나서). 먼저 치운다.
    try: page.evaluate(_LAYER_CLOSE)
    except Exception: pass
    page.wait_for_selector("g-th[obj-type='openLayer']", timeout=15000)
    for half in ("1", "2"):
        d = _open_layer(page, "g-th[obj-type='openLayer'][param-info*=\"'half':'%s'\"]" % half)
        if d is None:
            print(f"  [WARN] {half}반기 미참여 목록 수집 실패 — 이번 판정에서 제외")
            continue
        c = d.get("cells") or []
        out[half] = [c[i:i + 6] for i in range(0, len(c) - 5, 6)]   # 6칸 = 한 사람
    infos = page.evaluate("""() => [...document.querySelectorAll("span.s_button.opn[obj-type='openLayer']")]
        .map(e => e.getAttribute('param-info') || '')""") or []
    bigos = []
    for pi in infos:
        m = re.search(r"'lifmgno':'(\d+)'", pi)
        if not m:
            continue
        d = _open_layer(page, "span.s_button.opn[param-info*=\"'lifmgno':'%s'\"]" % m.group(1))
        if d and "비고" in (d.get("text") or ""):
            bigos.append(d["text"].split("비고", 1)[1])
    out["bigo"] = " ".join(" ".join(b.split()) for b in bigos)
    return out


def collect_branch(page, g):
    go(page, "left_sub3", "/share/care/view.meal_satisfaction_daynurse", "3-1-4.식사(간식) 만족도 조사 및 반영", g, marker="만족도")
    sat = page.evaluate(SAT_JS)
    try:
        unfinished = collect_unfinished(page)
    except Exception as e:      # 팝업이 안 열려도 종전 판정은 계속되게 (없으면 ②-2를 건너뛴다)
        print(f"  [WARN] 미참여 목록 수집 실패: {e}")
        unfinished = {}
    go(page, "left_sub6", "/share/safe/view.weekly_menu", "6-1.주간식단표", g, marker="식단")
    menu = page.evaluate(MENU_JS)
    return {"satisfaction": sat, "menu": menu, "unfinished": unfinished}

def merge_dashboard(judged):
    """dashboard_data.js 의 AUDIT_DATA 각 지점 item_results 에 33번 주입 (나머지 부분 보존)."""
    path = "audit_results/dashboard_data.js"
    raw = io.open(path, encoding="utf-8").read()
    prefix = "window.AUDIT_DATA = "
    i = raw.index(prefix) + len(prefix)
    obj, end = json.JSONDecoder().raw_decode(raw, i)
    hit = 0
    for br, res in judged.items():
        if br in obj:
            obj[br].setdefault("item_results", {})["33"] = res
            hit += 1
    newraw = raw[:i] + json.dumps(obj, ensure_ascii=False) + raw[end:]
    io.open(path, "w", encoding="utf-8").write(newraw)
    print(f"[대시보드 병합] {hit}개 지점에 33번 주입 → {path}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_merge = "--merge" in sys.argv
    keys = args or ["청주"]
    cfg = Config.load(config_path())
    today = datetime.datetime.now()
    out, judged = {}, {}
    with sync_playwright() as pw:
        for key in keys:
            b = next(x for x in cfg.branches if key in x.name)
            print(f"\n===== {b.name} =====")
            browser, page = login(pw, b.ctmnumb)
            try:
                g = extract_g_pammgno(page)
                data = collect_branch(page, g)
                out[b.name] = data
                res = judge_item33(data, today)
                judged[b.name] = res
                print("  수집:", json.dumps(data, ensure_ascii=False))
                print("  판정:", res["status"], res["sub_status"])
                print("       ", res["detail"])
            finally:
                browser.close()
    os.makedirs("audit_results", exist_ok=True)
    io.open("audit_results/item33_raw.json", "w", encoding="utf-8").write(
        json.dumps({"raw": out, "judged": judged}, ensure_ascii=False, indent=2))
    print("\n[저장] audit_results/item33_raw.json")
    if do_merge:
        merge_dashboard(judged)

if __name__ == "__main__":
    main()


def judge_avoid_food(results, cut: str = "2026.01.01", today: str | None = None):
    """항목 33①: 기간 내 신규 수급자의 욕구사정에 기피식품 기재 여부.

    - 욕구사정 영양상태 판단근거에 '기피식품'이 있으면 기재로 인정('없음' 포함, 매뉴얼 기준)
    - 기간 내 신규 수급자 없으면 예외(양호)
    - avoidFood 필드가 아예 없으면(구버전 스캔) 판정 보류 → (None, None)

    ★급여개시일이 아직 오지 않은 사람은 판정에서 뺀다(사용자 지적 2026-08-02).
      기준이 "급여제공 시작일까지 파악"이라 시작 전에는 욕구사정이 없는 게 정상인데,
      스캔이 개시일 전날 밤에 돌면 그 사람이 '미기재'로 잡혔다
      (실측: 급여개시 07-31 수급자 1명 / 스캔 07-30 22:55 → 오탐).
    반환: (status, note) 또는 (None, None)
    """
    from datetime import date as _date

    if today is None:
        today = f"{_date.today():%Y.%m.%d}"

    has_field = any("avoidFood" in n for p in results for n in (p.get("needs") or []))
    if not has_field:
        return None, None

    new, pending = [], []
    for p in results:
        starts = [e["d"] for e in (p.get("enroll") or [])
                  if e.get("k") == "급여개시일" and e.get("d")]
        if not starts or min(starts) < cut:
            continue
        (pending if min(starts) > today else new).append(p["name"])

    tail = (f" · 급여개시 전 {len(pending)}명 판정 제외({', '.join(pending[:3])})"
            if pending else "")
    if not new:
        return "양호", "①기피식품: 기간 내 신규 수급자 없음(예외)" + tail
    new = [p for p in results if p["name"] in set(new)]

    miss = [p["name"] for p in new if not any(n.get("avoidFood") for n in (p.get("needs") or []))]
    if miss:
        return "미흡", (f"①기피식품 미기재 {len(miss)}명"
                      f"({', '.join(miss[:5])}{'…' if len(miss) > 5 else ''})" + tail)
    return "양호", f"①기피식품 기재 확인(신규 {len(new)}명 전원)" + tail
