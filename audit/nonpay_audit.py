# -*- coding: utf-8 -*-
"""비급여 3자 대조 — 케어포 9-2(실제) ↔ 이용계약 공지 첨부 ↔ 공단 게시.

항목 18(정보제공)은 게시 '여부'만이 아니라 게시 '내용'이 실제와 맞는지가 평가 대상이다
(사용자 확정 2026-07-29: 실제 평가는 공지사항에 게시된 내용을 확인한다).
기준은 **케어포 9-2 요양급여 수가설정** — 실제 청구에 쓰는 값이다.

세 소스 전부 자동 수집된다:
  ① 케어포 9-2   left_sub9 / /basic/view.service_cost   (포털 로그인)
  ② 공단 게시     공식 오픈API getNonBenefitSttusDetailInfoList02 (로그인 불필요)
  ③ 이용계약 공지 기관 상세 공지사항 탭 → 글 상세 → 첨부(PDF/HWP)   (로그인 불필요)

★함정
- 공지사항 탭은 **POST(aTab=20)** 로만 채워진다. GET 하면 빈 화면이라 "로그인 전용"으로 오판하기 쉽다.
- 케어포 그리드는 <tr> 이 없다. <g-t> 안에 g-th/g-td 가 평평하게 깔리고 data-gt-row/col 로 위치가 정해진다.
- 등급외자는 케어포 9-2 에 칸이 없어 대조 불가 → 판정에서 제외한다.
- 케어포는 단일 계정이라 동시 접속 금지. 이 도구는 지점을 순차로만 돈다.

실행: py -X utf8 -m audit.nonpay_audit            (4지점 전체)
      py -X utf8 -m audit.nonpay_audit --branch 둔산점
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://www.longtermcare.or.kr"
DET = f"{BASE}/npbs/r/a/201/selectLtcoSrchDetail.web"
API = ("http://apis.data.go.kr/B550928/getLtcInsttDetailInfoService02"
       "/getNonBenefitSttusDetailInfoList02")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
DELAY = 2.0
RES = Path(__file__).resolve().parent.parent / "audit_results"

CELL = re.compile(r"<g-(?:th|td)([^>]*)>(.*?)</g-(?:th|td)>", re.S)
# 표 머리글은 '비급여 항목' 바로 뒤에 '금 액'. 본문 제14조의 '비급여 항목 등을 포함한…' 과
# 구분하려면 이 짝을 봐야 한다(처음엔 앞말만 찾아 본문 조항을 잘못 집었다).
TBL_HEAD = re.compile(r"비급여\s*항목\s*\n?\s*금\s*액")
WON = re.compile(r"([\d,]+)\s*원")


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _num(s: str) -> int | None:
    m = re.search(r"([\d,]{3,})", s or "")
    return int(m.group(1).replace(",", "")) if m else None


# ── ① 케어포 9-2 ────────────────────────────────────────────────────────────
def parse_carefor(page_html: str) -> dict:
    """'기관 비급여 수가 정보' 그리드 → {applied, meals:{아침/점심/저녁}, snack, snack_unit}."""
    i = page_html.find("기관 비급여 수가 정보")
    if i < 0:
        return {}
    j = page_html.find("<g-t", i)
    seg = page_html[j:page_html.find("</g-t>", j)]
    rows: dict[int, dict[int, str]] = defaultdict(dict)
    for m in CELL.finditer(seg):
        r = re.search(r'data-gt-row="(\d+)"', m.group(1))
        c = re.search(r'data-gt-col="(\d+)"', m.group(1))
        if r and c:
            rows[int(r.group(1))][int(c.group(1))] = _plain(m.group(2))

    out: dict = {"meals": {}}
    for r in sorted(rows):
        cells = [rows[r].get(c, "") for c in sorted(rows[r])]
        line = " ".join(x for x in cells if x)
        if "적용일" in line:
            out["applied"] = line.split("|")[-1].replace("비급여 수가 적용일", "").strip()
        elif "식사재료비" in line and "월한도" not in line:
            named = re.findall(r"(아침|점심|저녁)\s*:\s*([\d,]+)\s*원", line)
            if named:
                out["meals"] = {k: int(v.replace(",", "")) for k, v in named}
            else:
                v = _num(line)
                if v:
                    out["meals"] = {"식사": v}
            out["meal_unit"] = "1식" if "(1식)" in line else ("1일" if "(1일)" in line else "")
        elif "간식비" in line and "월한도" not in line:
            out["snack"] = _num(line)
            out["snack_unit"] = "1식" if "(1식)" in line else ("1일" if "(1일)" in line else "")
    return out


def fetch_carefor(branch_name: str, ctmnumb: str) -> dict:
    """케어포에 로그인해 9-2 를 열고 그리드를 파싱. Playwright 필요."""
    from playwright.sync_api import sync_playwright

    from src.carefor_client import _navigate_spa, build_spa_hash
    from .explore_pages import login

    with sync_playwright() as p:
        browser, page = login(p, ctmnumb, headless=True)
        try:
            _navigate_spa(page, "https://dn.carefor.co.kr/#" + build_spa_hash(
                "left_sub9", "/basic/view.service_cost", "9-2.요양급여 수가설정", ""))
            page.wait_for_timeout(5000)
            return parse_carefor(page.evaluate("document.body.innerHTML"))
        finally:
            browser.close()


# ── ② 공단 게시(공식 API) ───────────────────────────────────────────────────
def fetch_portal(sym: str, key: str) -> list[dict]:
    """★urllib 은 이 호스트에서 간헐 타임아웃 → curl 로 부른다(심평원 함정과 같은 계열)."""
    url = f"{API}?serviceKey={key}&longTermAdminSym={sym}&numOfRows=50&pageNo=1"
    body = subprocess.run(["curl", "-s", "-m", "30", url],
                          capture_output=True, text=True, encoding="utf-8").stdout
    out = []
    for it in re.findall(r"<item>(.*?)</item>", body, re.S):
        g = lambda k: (re.search(rf"<{k}>([^<]*)</{k}>", it) or [None, ""])[1]  # noqa: E731
        out.append({"kind": g("nonpayKind"), "amt": _num(g("nonpayTgtAmt")),
                    "base": g("prodBase"), "upt": g("uptDt")})
    return out


# ── ③ 이용계약 공지 첨부 ────────────────────────────────────────────────────
def notice_list(s: requests.Session, sym: str) -> list[dict]:
    s.get(f"{DET}?ltcAdminSym={sym}&adminPttnCd=B03", timeout=30)
    t = s.post(DET, data={"ltcAdminSym": sym, "adminPttnCd": "B03", "aTab": "20"},
               headers={"Referer": f"{DET}?ltcAdminSym={sym}&adminPttnCd=B03"}, timeout=30).text
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
        a = re.search(r'href="(/npbs/r/a/201/selectBlbdArtiDtl\.web\?[^"]+)"', row)
        if not a:
            continue
        title = _plain(re.sub(r"<!--.*?-->", "", row[row.find(a.group(0)):], flags=re.S))
        half = len(title) // 2
        if half and title[:half].strip() == title[half:].strip():
            title = title[:half].strip()
        out.append({"title": title, "url": html.unescape(a.group(1))})
    return out


def contract_year(title: str) -> str | None:
    """지점마다 표기가 제각각이다 — '2026년 …이용계약에 관한 사항'(둔산·청주),
    '(주야간보호)' 삽입(서구), '…이용에 관한 사항_2025년'(천안, '계약'조차 없음).
    그래서 '장기요양급여'+'이용'+연도 로만 느슨하게 본다."""
    if "장기요양급여" not in title or "이용" not in title:
        return None
    m = re.search(r"(20\d\d)\s*년", title)
    return m.group(1) if m else None


def contract_nonpay(s: requests.Session, url: str) -> tuple[list[tuple[str, str]], str]:
    t = s.get(BASE + url, timeout=30, headers={"Referer": DET}).text
    a = re.search(r'href="(/npbs/attachfile/sendFile\.web\?[^"]+)"', t)
    if not a:
        return [], "첨부없음"
    time.sleep(DELAY)
    blob = s.get(BASE + html.unescape(a.group(1)), timeout=60, headers={"Referer": DET}).content
    if blob[:4] == b"%PDF":
        txt, is_pdf, kind = _pdf_text(blob), True, "PDF"
    else:
        txt, is_pdf, kind = _hwp_text(blob), False, "HWP"
    if txt is None:
        return [], f"{kind} 파서 없음"
    return _parse_table(txt, is_pdf), kind


def _pdf_text(blob: bytes) -> str | None:
    try:
        import io

        import pdfplumber
    except ImportError:
        return None
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        return "\n".join((pg.extract_text() or "") for pg in pdf.pages)


def _hwp_text(blob: bytes) -> str | None:
    """HWP5 = OLE 복합문서. BodyText/Section* 을 (압축이면 raw-deflate 해제 후) 레코드로 읽어
    tagID 67(PARA_TEXT)만 모은다. 텍스트는 UTF-16LE, 0~31 은 제어문자이고 일부는 8 wchar 를 먹는다."""
    try:
        import io
        import struct
        import zlib

        import olefile
    except ImportError:
        return None
    ext = {1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23}
    f = olefile.OleFileIO(io.BytesIO(blob))
    try:
        compressed = bool(f.openstream("FileHeader").read()[36] & 1)
        parts = []
        for entry in sorted(e for e in f.listdir() if e[0] == "BodyText"):
            buf = f.openstream("/".join(entry)).read()
            if compressed:
                buf = zlib.decompress(buf, -15)
            i, n = 0, len(buf)
            while i + 4 <= n:
                (v,) = struct.unpack_from("<I", buf, i); i += 4
                tag, size = v & 0x3FF, (v >> 20) & 0xFFF
                if size == 0xFFF:
                    (size,) = struct.unpack_from("<I", buf, i); i += 4
                if tag == 67:
                    data, j, out = buf[i:i + size], 0, []
                    while j + 2 <= len(data):
                        (c,) = struct.unpack_from("<H", data, j)
                        if c in ext:
                            j += 16
                        elif c < 32:
                            out.append("\n" if c in (10, 13) else "")
                            j += 2
                        else:
                            out.append(chr(c)); j += 2
                    parts.append("".join(out))
                i += size
        return "\n".join(parts)
    finally:
        f.close()


def _parse_table(txt: str, is_pdf: bool) -> list[tuple[str, str]]:
    m = TBL_HEAD.search(txt)
    if not m:
        return []
    seg = [l.strip() for l in txt[m.end():m.end() + 700].split("\n") if l.strip()]
    rows: list[tuple[str, str]] = []
    if is_pdf:
        # ★금액을 '숫자'로만 잡으면 '식사 재료비 1회' 의 1 을 금액으로 집는다(실제로 그랬다).
        #   PDF 는 2단 조판이라 오른쪽 단(방문요양 수가)이 같은 줄에 섞여 오니 '처음' 것만.
        amt = re.compile(r"(실비|[\d,]{3,}\s*원\s*이내|[\d,]{3,})")
        for line in seg[:8]:
            if re.match(r"^-\s*\d+\s*-", line):
                break
            a = amt.search(line)
            if a and a.start() > 0:
                rows.append((line[:a.start()].strip(), a.group(1).strip()))
    else:
        i = 0
        while i + 1 < len(seg) and len(rows) < 8:
            if "별첨" in seg[i] or "수가" in seg[i]:
                break
            rows.append((seg[i], seg[i + 1])); i += 2
    return rows


# ── 대조 ────────────────────────────────────────────────────────────────────
_SNACK = re.compile(r"간식")
_MEAL = re.compile(r"식사|조식|중식|석식|아침|점심|저녁|죽식")


def compare(cf: dict, portal: list[dict], contract: list[tuple[str, str]]) -> list[dict]:
    """케어포(실제)를 기준으로 게시·계약서를 본다. 등급외자는 케어포에 칸이 없어 제외.

    ★식사와 간식을 반드시 **갈라서** 본다. 금액만 뭉쳐 비교하면, 둔산처럼
      '아침 550원'과 '간식 550원'이 우연히 같을 때 아침 미게시를 통과시킨다(실제 오탐).
    공단 게시 nonpayKind: 1=식사류 · 5=간식 · 7=등급외자(제외).
    """
    issues: list[dict] = []
    meals = cf.get("meals") or {}
    if not meals:
        return [{"level": "확인불가", "what": "케어포 9-2 수가를 읽지 못함"}]

    # ★게시 금액칸의 '단위'는 지점 자유다 — 둔산·서구·천안은 1식 단가, 청주는 하루치를 넣고
    #   산출근거에 '일 3,300원X2식' 처럼 단가를 밝힌다(6,600 = 3,300×2). 금액칸만 비교하면
    #   청주가 통째로 미흡으로 뒤집힌다(실제 오탐). 산출근거에 적힌 금액도 인정 후보에 넣는다.
    def _amts(kind: str) -> set[int]:
        out: set[int] = set()
        for p in portal:
            if p["kind"] != kind:
                continue
            if p["amt"]:
                out.add(p["amt"])
            for m in re.finditer(r"([\d,]{3,})\s*원?", p.get("base") or ""):
                v = _num(m.group(1))
                if v:
                    out.add(v)
        return out

    p_meal = _amts("1")
    p_snack = _amts("5")
    c_meal = {_num(v) for n, v in contract if _MEAL.search(n) and not _SNACK.search(n)}
    c_snack = {_num(v) for n, v in contract if _SNACK.search(n)}
    c_meal.discard(None); c_snack.discard(None)

    # ★'못 읽음'을 '일치'로 흘려보내지 않는다. 아래 대조는 집합이 비면 건너뛰게 되어 있어,
    #   첨부 파싱이 실패해도 조용히 통과한다 — 판정 결과만 보면 구분이 안 된다.
    if not portal:
        issues.append({"level": "확인불가", "what": "공단 게시 비급여를 못 읽음(API 무응답/미등록)"})
    if not contract:
        issues.append({"level": "확인불가", "what": "이용계약 첨부의 비급여 표를 못 읽음 — 계약서 대조 생략됨"})
    else:
        if not c_meal:
            issues.append({"level": "확인불가", "what": f"계약서에서 식사 항목을 못 찾음(읽은 행: {[n for n, _ in contract]})"})
        if cf.get("snack") and not c_snack:
            issues.append({"level": "확인불가", "what": f"계약서에서 간식 항목을 못 찾음(읽은 행: {[n for n, _ in contract]})"})

    # 소스를 못 읽었으면 그 쪽 대조는 아예 하지 않는다 — '못 읽음'을 '위반'으로 찍으면
    # 무응답 한 번에 전 항목이 미흡으로 뒤집힌다(고치기 전 실제로 그랬다).
    do_portal = bool(portal)
    do_contract = bool(contract) and bool(c_meal or c_snack)

    for name, amt in sorted(meals.items(), key=lambda x: x[1]):
        if do_portal and amt not in p_meal:
            issues.append({"level": "미흡",
                           "what": f"식사({name}) {amt:,}원 — 공단 게시 식사항목에 없음",
                           "게시": sorted(f"{a:,}" for a in p_meal)})
        if do_contract and c_meal and amt not in c_meal:
            issues.append({"level": "미흡",
                           "what": f"식사({name}) {amt:,}원 — 이용계약서 식사항목에 없음",
                           "계약서": sorted(f"{a:,}" for a in c_meal)})

    sn = cf.get("snack")
    if sn:
        unit = cf.get("snack_unit") or ""
        if do_portal:
            if not p_snack:
                issues.append({"level": "미흡", "what": f"간식 {sn:,}원({unit}) — 공단 게시에 간식 항목 없음"})
            elif sn not in p_snack:
                issues.append({"level": "미흡", "what": f"간식 {sn:,}원({unit}) — 공단 게시 간식과 다름",
                               "게시": sorted(f"{a:,}" for a in p_snack)})
        if do_contract and c_snack and sn not in c_snack:
            issues.append({"level": "미흡", "what": f"간식 {sn:,}원({unit}) — 이용계약서 간식과 다름",
                           "계약서": sorted(f"{a:,}" for a in c_snack)})
    return issues


def read_carefor_page(page) -> dict:
    """로그인된 page 를 9-2 로 옮겨 비급여 수가만 읽는다(네트워크 대조는 하지 않음).

    ★collector 는 이걸 `with sync_playwright()` **안에서** 부른다. 항목 판정부는
      browser.close() 뒤라 거기서 page 를 만지면 'Event loop is closed' 로 죽는다(실측).
      그래서 '수집(page 필요)'과 '대조(네트워크만)'를 갈라 놓았다.
    """
    from src.carefor_client import _navigate_spa, build_spa_hash

    _navigate_spa(page, "https://dn.carefor.co.kr/#" + build_spa_hash(
        "left_sub9", "/basic/view.service_cost", "9-2.요양급여 수가설정", ""))
    page.wait_for_timeout(5000)
    return parse_carefor(page.evaluate("document.body.innerHTML"))


def compare_collected(cf: dict, sym: str, key: str) -> dict:
    portal = fetch_portal(sym, key)
    s = requests.Session(); s.headers.update({"User-Agent": UA})
    years: dict[str, dict] = {}
    for n in notice_list(s, sym):
        y = contract_year(n["title"])
        if y and y not in years:
            years[y] = n
    latest = max(years) if years else None
    contract, kind = ([], "공지없음")
    if latest:
        time.sleep(DELAY)
        contract, kind = contract_nonpay(s, years[latest]["url"])
    res = {"carefor": cf, "portal": portal, "contract_years": sorted(years),
           "contract_year": latest, "contract_kind": kind, "contract": contract}
    res["issues"] = compare(cf, portal, contract)
    return res


def to_judgement(res: dict, cutoff: str | None = None) -> dict:
    """3자 대조 결과 → 항목 18 판정 조각. 게시 '내용'이 실제와 다르면 미흡.

    개소 연도부터의 이용계약 공지 게시도 함께 본다(개소 전 연도는 요구하지 않는다 —
    서구점 2025-03-01 개소라 2024년 공지가 없는 게 정상인데 미흡으로 찍었던 오판이 있었다).
    """
    from datetime import date

    bad = [i for i in res["issues"] if i["level"] == "미흡"]
    unk = [i for i in res["issues"] if i["level"] == "확인불가"]

    miss_years: list[str] = []
    if cutoff:
        start = int(str(cutoff)[:4])
        need = [str(y) for y in range(start, date.today().year + 1)]
        miss_years = [y for y in need if y not in res["contract_years"]]

    if miss_years:
        return {"status": "미흡", "sub_status": {"①": "미흡"},
                "detail": f"[비급여 게시내용] 이용계약 공지 미게시: {', '.join(miss_years)}년"}
    if bad:
        return {"status": "미흡", "sub_status": {"①": "미흡"},
                "detail": "[비급여 게시내용] 케어포 9-2 기준 불일치 — " + " · ".join(i["what"] for i in bad)}
    if unk:
        return {"status": "주의",
                "detail": "[비급여 게시내용] " + " · ".join(i["what"] for i in unk)}
    return {"status": "양호",
            "detail": f"[비급여 게시내용] 케어포 9-2 ↔ 이용계약({res['contract_year']}) ↔ 공단 게시 3자 일치"}


def run(branch_name: str, ctmnumb: str, sym: str, key: str) -> dict:
    from .collect_ltc_public import _ltc_key  # noqa: F401  (키 경로 일원화 확인용)

    cf = fetch_carefor(branch_name, ctmnumb)
    time.sleep(DELAY)
    res = compare_collected(cf, sym, key)   # collector 와 같은 경로를 쓴다(로직 갈라짐 방지)
    res["branch"] = branch_name
    return res


def main() -> int:
    from src.config import Config, config_path

    from .collect_ltc_public import _ltc_key

    ap = argparse.ArgumentParser()
    ap.add_argument("--branch")
    args = ap.parse_args()

    key = _ltc_key()
    if not key:
        print("ERROR: 공단 API 키(LTC_API_KEY)가 없습니다."); return 1
    cfg = Config.load(config_path())
    syms = {}
    for f in RES.glob("롱텀공개_*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        syms[d["branch_name"]] = d["ltc_admin_sym"]

    out = []
    for b in cfg.branches:
        if args.branch and b.name != args.branch:
            continue
        sym = syms.get(b.name)
        if not sym:
            print(f"[{b.name}] 기관기호 없음 — 롱텀공개_*.json 먼저 수집 필요"); continue
        print(f"\n{'='*70}\n■ {b.name}")
        r = run(b.name, b.ctmnumb, sym, key)
        cf = r["carefor"]
        print(f"  케어포 9-2  적용 {cf.get('applied','?')} · 식사 {cf.get('meals')} · 간식 {cf.get('snack')}({cf.get('snack_unit')})")
        print(f"  공단 게시    " + " / ".join(f"{p['amt']:,}({p['base'][:18]})" for p in r["portal"]))
        print(f"  계약서({r['contract_year']} {r['contract_kind']})  " + " · ".join(f"{n} {v}" for n, v in r["contract"]))
        print(f"  공지 연도    {r['contract_years']}")
        if r["issues"]:
            for i in r["issues"]:
                print(f"   ★{i['level']}: {i['what']}")
        else:
            print("   ✅ 3자 일치")
        out.append(r)

    RES.mkdir(parents=True, exist_ok=True)
    (RES / "비급여_3자대조.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {RES/'비급여_3자대조.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
