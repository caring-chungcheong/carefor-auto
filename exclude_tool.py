# -*- coding: utf-8 -*-
"""
상담 미입력 '제외 선택' 도구 — 미입력 목록을 보고 번호로 골라 제외번호에 자동 추가.

제외번호 시트: '충청본부_상담제외번호(자동관리)' (앱 계정 소유, 앱이 쓰기/웹앱이 읽기).
  → consult_report.EXCL_SSID / EXCL_SHEET. 본사 시트는 건드리지 않음.
한 번 추가하면 영구 제외, 매일 발송(슬랙·허브·엑셀)에 다음날 자동 반영.

실행:
  py -X utf8 exclude_tool.py          # 미입력 목록 → 번호 선택 → 제외 추가
  py -X utf8 exclude_tool.py --list   # 현재 제외번호 목록만 보기
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")

from openpyxl import Workbook
import keyring

import consult_report as cr

RC = os.path.join(os.path.expanduser("~"), ".clasprc.json")
SSID = cr.EXCL_SSID
SHEET = cr.EXCL_SHEET


def _token() -> str:
    st = json.load(open(RC, encoding="utf-8"))
    c = st["tokens"]["default"]
    data = urllib.parse.urlencode({
        "client_id": c["client_id"], "client_secret": c["client_secret"],
        "refresh_token": c["refresh_token"], "grant_type": "refresh_token"}).encode()
    return json.load(urllib.request.urlopen(
        urllib.request.Request("https://oauth2.googleapis.com/token", data=data), timeout=30))["access_token"]


def read_excl() -> list:
    web = keyring.get_password("carefor-auto", "consult_webhook_url")
    u = web + "&ssid=" + SSID + "&sheet=" + urllib.parse.quote(SHEET)
    r = json.load(urllib.request.urlopen(urllib.request.Request(u), timeout=40))
    return r.get("values", [])


def write_excl(rows: list) -> None:
    """제외번호 시트 전체를 rows로 덮어쓰기 (헤더 포함). Drive media PATCH → Google Sheets 변환."""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    req = urllib.request.Request(
        f"https://www.googleapis.com/upload/drive/v3/files/{SSID}?uploadType=media",
        data=buf.getvalue(), method="PATCH",
        headers={"Authorization": "Bearer " + _token(),
                 "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
    urllib.request.urlopen(req, timeout=60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="현재 제외번호만 보기")
    args = ap.parse_args()

    excl = read_excl()
    header = excl[0] if excl else ["번호", "사유", "추가일"]
    existing = {cr._norm_phone(row[0]) for row in excl[1:] if row}

    if args.list:
        print(f"현재 제외번호 {len(existing)}건:")
        for row in excl[1:]:
            print("  ", " | ".join(str(c) for c in row))
        return

    rows = cr.load_rows_from_webhook()
    miss = [r for r in rows if r.get("missing")]
    if not miss:
        print("현재 미입력이 없습니다. 👍")
        return
    miss.sort(key=lambda r: (r["center"], r["consult_date"]))

    print(f"=== 미입력 {len(miss)}건 — 제외할(주간보호 아닌) 항목을 고르세요 ===")
    print("     (연락처는 화면에 표시하지 않습니다)\n")
    for i, r in enumerate(miss, 1):
        print(f"[{i:2}] {r['center'][:7]:7} {r['consult_date']}  {(r['summary'] or '')[:48]}")

    sel = input("\n제외할 번호(쉼표, 예: 1,3,5 / 취소=엔터): ").strip()
    if not sel:
        print("취소했습니다.")
        return
    idxs = [int(x) for x in sel.replace(" ", "").split(",") if x.isdigit()]
    picked = [miss[i - 1] for i in idxs if 1 <= i <= len(miss)]
    if not picked:
        print("선택된 항목이 없습니다.")
        return

    reason = input("사유(공통, 엔터=비대상): ").strip() or "비대상"
    today = date.today().isoformat()
    new_rows = []
    for r in picked:
        if cr._norm_phone(r["phone"]) not in existing:
            new_rows.append([r["phone"], f"{reason} ({r['center']} {r['consult_date']})", today])
    if not new_rows:
        print("선택한 건은 이미 제외돼 있습니다.")
        return

    print("\n추가할 항목:")
    for nr in new_rows:
        print("  +", nr[0], "—", nr[1])
    if input("\n추가할까요? (y/N): ").strip().lower() != "y":
        print("취소했습니다.")
        return

    write_excl(excl + new_rows)
    print(f"\n✅ {len(new_rows)}건 제외 추가 완료. 매일 발송(슬랙·허브·엑셀)에 다음날 자동 반영됩니다.")


if __name__ == "__main__":
    main()
