# -*- coding: utf-8 -*-
"""정기검사 기간 3자 대조 — 도로교통공단(cyberts) ↔ 차량관리 앱 ↔ 노션.

왜: 앱은 매일 cyberts 값을 받아 시트에 저장하지만(자동), 노션은 사람이 수동 갱신한
    별도 저장소다. 셋이 일치하는지(특히 노션 댓글의 '자동차검사 가능기간')를 원 단위로 본다.

세 소스:
  · cyberts.kr  = 공단 정기검사 가능기간 (start~end)  ← 진실(authoritative). 독립 재조회.
  · 차량관리 앱 = 구글시트 inspectStart/End         ← fetch_vehicle_data(getAll)
  · 노션        = '검사유효기간' 속성(만료일=순수검사일) + 댓글 '가능기간 start~end'
                  (src.notion_client.fetch_inspect_dates)

실행: py -X utf8 -m audit.verify_inspect            # 3자 전부(노션 토큰 필요)
      py -X utf8 -m audit.verify_inspect --no-notion  # 공단↔앱만
      py -X utf8 -m audit.verify_inspect --no-cyberts # 앱↔노션만(빠름)
"""
from __future__ import annotations

import sys


def norm(v) -> str:
    return str(v or "").strip().replace(" ", "")


def car_key(no: str) -> str:
    return norm(no)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    do_cyberts = "--no-cyberts" not in sys.argv
    do_notion = "--no-notion" not in sys.argv

    sys.path.insert(0, ".")
    from fetch_cars import fetch_vehicle_data

    # ── 1) 차량관리 앱 (기준 목록) ──
    print("차량관리 앱 데이터 로드...", flush=True)
    data = fetch_vehicle_data()
    app: dict[str, dict] = {}
    for branch, cars in data.items():
        for c in cars:
            k = car_key(c.get("carNumber", ""))
            if not k:
                continue
            app[k] = {"branch": branch, "no": c.get("carNumber", ""),
                      "start": norm(c.get("inspectStart")), "end": norm(c.get("inspectEnd"))}
    print(f"  앱 차량 {len(app)}대")

    # ── 2) 공단 cyberts (독립 재조회) ──
    cyb: dict[str, tuple] = {}
    if do_cyberts:
        print("공단(cyberts.kr) 정기검사 가능기간 재조회... (몇 분 소요)", flush=True)
        try:
            from fetch_cars import fetch_cyberts_inspect_dates
            raw = fetch_cyberts_inspect_dates(data, headless=True)
            cyb = {car_key(k): (norm(s), norm(e)) for k, (s, e) in raw.items()}
            print(f"  공단 조회 {len(cyb)}대")
        except Exception as ex:
            print(f"  ⚠️ 공단 조회 실패 — 이 대조는 건너뜀: {ex}")
            do_cyberts = False

    # ── 3) 노션 ──
    notion: dict[str, dict] = {}
    if do_notion:
        print("노션 차량현황 조회...", flush=True)
        try:
            from src.notion_client import fetch_inspect_dates
            raw = fetch_inspect_dates()
            notion = {car_key(k): {"start": norm(v.get("inspect_start")),
                                   "end": norm(v.get("inspect_end"))}
                      for k, v in raw.items()}
            print(f"  노션 차량 {len(notion)}대")
        except Exception as ex:
            print(f"  ⚠️ 노션 조회 실패 — 토큰 필요: {ex}")
            do_notion = False

    # ── 대조 ──
    print("\n================ 정기검사 기간 대조 ================")
    mism_ca, mism_an, missing_notion = [], [], []
    for k, a in sorted(app.items(), key=lambda x: (x[1]["branch"], x[1]["no"])):
        line = f"{a['branch']} {a['no']}  앱 {a['start']}~{a['end']}"
        # 공단 vs 앱
        if do_cyberts:
            if k in cyb:
                cs, ce = cyb[k]
                if (cs, ce) != (a["start"], a["end"]):
                    mism_ca.append((a, ("공단", f"{cs}~{ce}")))
            else:
                mism_ca.append((a, ("공단", "조회안됨")))
        # 앱 vs 노션
        if do_notion:
            if k in notion:
                ns, ne = notion[k]["start"], notion[k]["end"]
                if (ns, ne) != (a["start"], a["end"]):
                    mism_an.append((a, ("노션", f"{ns}~{ne}")))
            else:
                missing_notion.append(a)

    def dump(title, items):
        print(f"\n■ {title}: {len(items)}건")
        for a, (src, val) in items:
            print(f"   {a['branch']} {a['no']}: 앱 {a['start']}~{a['end']}  ≠  {src} {val}")

    if do_cyberts:
        dump("공단(cyberts) ≠ 앱", mism_ca)
        if not mism_ca:
            print("\n■ 공단(cyberts) ≠ 앱: 0건  ✅ 전부 일치")
    if do_notion:
        dump("노션 ≠ 앱", mism_an)
        if not mism_an:
            print("\n■ 노션 ≠ 앱: 0건  ✅ 전부 일치")
        if missing_notion:
            print(f"\n■ 앱엔 있는데 노션에 없는 차량: {len(missing_notion)}건")
            for a in missing_notion:
                print(f"   {a['branch']} {a['no']}")

    print("\n==================================================")
    print(f"요약: 앱 {len(app)}대 · "
          f"공단대조 {'ON' if do_cyberts else 'OFF'}({len(mism_ca)}불일치) · "
          f"노션대조 {'ON' if do_notion else 'OFF'}({len(mism_an)}불일치, {len(missing_notion)}누락)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
