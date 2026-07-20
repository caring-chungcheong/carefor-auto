# -*- coding: utf-8 -*-
"""노션 차량현황의 보험(보험사·만기) → 차량관리 시트 `_보험` 탭 업로드 + 앱 표시.

흐름: 노션(fetch_insurance) → 이 스크립트 → 정비이력 웹앱 syncMaintenance(insurance) → `_보험` 탭 → 앱 카드.

실행: py -X utf8 -m audit.push_insurance [--dry]
전제: NOTION_TOKEN(환경변수 또는 keyring). 로컬엔 없어 **클라우드(GitHub Actions)** 에서 돈다.

방침(사용자):
  - 보험사·만기는 노션에서 읽음. 만기 = 보험증서 파일명 앞 8자리(YYYYMMDD).
  - 보험기간↔차량번호가 상이/누락/파싱실패인 건은 **빼고** 나머지만 올린 뒤, **오류건만 보고**한다.
  - 시트 write 는 웹앱(익명 공개) POST 라 구글 인증 불필요. 보험만 sync 하므로 정비이력·타이어는 안 건드림.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")


def _norm(s: str) -> str:
    """차량번호 공백 제거 — 앱 carKey·정비이력(norm_num)과 동일한 조인 표기."""
    return re.sub(r"\s+", "", str(s or ""))

# 정비이력 전용 웹앱(= push_maintenance_to_sheet 와 동일). insurance 만 보내면 _보험 탭만 갱신된다.
API = ("https://script.google.com/macros/s/"
       "AKfycbwtdykb6e2NGRoP6pBJVCYoh2xP5uA3ZpOMoogUIAZ0hlCjP4P48-dvq4kAmGS1uwXqFw/exec")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="업로드 없이 미리보기만")
    args = ap.parse_args()

    from src.notion_client import fetch_insurance
    ins, errors = fetch_insurance()

    # INS_HEADERS = ['지점','차량번호','차량명','보험사','보험만기','증서파일명']
    rows = [[v["branch"], _norm(car), v["model"], v["insurer"], v["expiry"], v["cert"]]
            for car, v in sorted(ins.items(), key=lambda kv: (kv[1]["branch"], kv[0]))]

    print(f"업로드 대상: {len(rows)}대 · 제외(오류) {len(errors)}건\n")
    for r in rows:
        print(f"  {r[0][:4]:<5} {r[1]:<10} {r[3]:<8} 만기 {r[4]}")

    if errors:
        print("\n[오류/제외 건 — 확인 필요]")
        for e in errors:
            extra = f" ({e['cert']})" if e.get("cert") else ""
            print(f"  ⚠ {e.get('branch','')[:4]:<5} {e['car']:<10} {e['reason']}{extra}")
    else:
        print("\n오류 없음.")

    if args.dry:
        print("\n--dry: 업로드 안 함")
        return

    body = json.dumps({"action": "syncMaintenance", "insurance": rows}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    resp = json.load(urllib.request.urlopen(req, timeout=120))
    if not resp.get("ok"):
        print(f"\n업로드 실패: {resp.get('error')}")
        sys.exit(1)
    print(f"\n업로드 완료: {resp['data']}")


if __name__ == "__main__":
    main()
