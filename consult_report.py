# -*- coding: utf-8 -*-
"""
신규상담 ↔ 상담시트 입력 여부 현황 → 슬랙 공지

데이터 소스: 구글시트 '주보_충청본부_센터 현황' > '신규상담 세부사항' 탭
  (본사에서 매일 전일자 기준 자동 갱신, 상담시트 입력 여부 Y/N 포함)

사용:
  py -X utf8 consult_report.py --tsv <파일경로>          # TSV 파일로 실행 (테스트용)
  py -X utf8 consult_report.py                           # Apps Script webhook에서 데이터 로드
  옵션: --channel <채널ID>  --dry-run(전송 없이 미리보기)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")

try:
    import keyring
except ImportError:  # GitHub Actions에서는 env로 대체
    keyring = None


def _secret(env_name: str, keyring_key: str) -> str | None:
    v = os.environ.get(env_name)
    if v:
        return v
    return keyring.get_password(SERVICE, keyring_key) if keyring else None

SERVICE = "carefor-auto"
KEY_BOT_TOKEN = "slack_bot_token"
KEY_CONSULT_WEBHOOK = "consult_webhook_url"  # Apps Script 웹앱 URL (독립 스크립트)

TEST_CHANNEL = "C0BC37EB38C"  # #차량관리 (테스트 방)
SHEET_NAME = "신규상담 세부사항"

# 표 표시 순서 (짧은 이름: 시트의 센터명 매칭용 접두)
CENTER_ORDER = [("둔산", "대전둔산점"), ("서구", "대전서구점"),
                ("천안", "천안점"), ("청주오창", "청주오창점")]


# ---------- 표 정렬 유틸 (한글 2칸 폭) ----------
def _w(s: str) -> int:
    return sum(2 if ord(c) > 0x1100 else 1 for c in s)


def _rpad(s: str, width: int) -> str:
    return s + " " * max(0, width - _w(s))


def _lpad(s: str, width: int) -> str:
    return " " * max(0, width - _w(s)) + s


# ---------- 데이터 로드 ----------
def load_rows_from_tsv(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) >= 14 and c[0][:4].isdigit() and "년" in c[0]:
                rows.append(_row(c))
    return rows


def load_rows_from_webhook() -> list[dict]:
    url = _secret("CONSULT_WEBHOOK_URL", KEY_CONSULT_WEBHOOK)
    if not url:
        raise SystemExit("consult_webhook_url 자격증명이 없습니다. Apps Script 배포 후 등록하세요.")
    req = urllib.request.Request(f"{url}{'&' if '?' in url else '?'}sheet={urllib.parse.quote(SHEET_NAME)}")
    with urllib.request.urlopen(req, timeout=60) as res:
        data = json.loads(res.read().decode("utf-8"))
    if not data.get("ok"):
        raise SystemExit(f"webhook 오류: {data.get('error')}")
    rows = []
    for c in data["values"]:
        c = [str(x) if x is not None else "" for x in c]
        if len(c) >= 14 and c[0][:4].isdigit() and "년" in c[0]:
            rows.append(_row(c))
    return rows


def _row(c: list[str]) -> dict:
    return {
        "yearmonth": c[0].strip(),      # 연월
        "center": c[4].strip(),         # 센터명
        "week": c[5].strip(),           # 해당 주차
        "consult_date": c[6].strip(),   # 상담일자
        "start_date": c[7].strip(),     # 급여개시일자
        "phone": c[9].strip(),          # 고객 번호
        "sheet_entered": c[10].strip(), # 상담시트 입력 여부 Y/N
        "admitted": c[11].strip(),      # 수급자 입소 여부 Y/N
        "summary": c[13].strip() if len(c) > 13 else "",  # AI 요약
    }


# ---------- 메시지 생성 ----------
def build_message(rows: list[dict], today: date) -> str:
    weekday = "월화수목금토일"[today.weekday()]
    title = f"📋 신규상담 상담시트 입력 현황 {today.strftime('%Y.%m.%d')}({weekday})"

    by_center = {}
    for r in rows:
        by_center.setdefault(r["center"], []).append(r)

    names, totals, misses, rates = [], [], [], []
    for short, full in CENTER_ORDER:
        grp = by_center.get(full, [])
        n_total = len(grp)
        n_miss = sum(1 for r in grp if r["sheet_entered"] == "N")
        names.append(short)
        totals.append(str(n_total))
        misses.append(str(n_miss))
        rates.append(f"{round(n_miss / n_total * 100)}%" if n_total else "-")

    LABEL_W = 16
    col_ws = [max(_w(n), 4) + 2 for n in names]
    header = _rpad("", LABEL_W) + "".join(_lpad(n, w) for n, w in zip(names, col_ws))
    sep = "─" * (LABEL_W + sum(col_ws))
    lines = [header, sep]
    for label, vals in [("신규상담(누적)", totals), ("시트 미입력", misses), ("미입력률", rates)]:
        lines.append(_rpad(label, LABEL_W) + "".join(_lpad(v, w) for v, w in zip(vals, col_ws)))
    table = "\n".join(lines)

    msg = f"{title}\n\n```\n{table}\n```"

    # 입소 완료인데 상담시트 미입력 — 우선 조치 대상
    urgent = [r for r in rows if r["admitted"] == "Y" and r["sheet_entered"] == "N"]
    if urgent:
        msg += f"\n\n⚠️ *입소 완료인데 상담시트 미입력: {len(urgent)}건*"
        for r in sorted(urgent, key=lambda x: (x["center"], x["consult_date"])):
            msg += f"\n· {r['center']} | 상담일 {r['consult_date']} | {r['phone']}"

    # 최근 주차 미입력 (이번 달 기준)
    ym = f"{today.year}년 {today.month:02d}월"
    recent = [r for r in rows if r["sheet_entered"] == "N" and r["yearmonth"] == ym]
    if recent:
        msg += f"\n\n📝 *{today.month}월 신규상담 중 미입력: {len(recent)}건*"
        for r in sorted(recent, key=lambda x: (x["center"], x["consult_date"])):
            msg += f"\n· {r['center']} | 상담일 {r['consult_date']} | {r['phone']}"

    msg += "\n\n상담시트 입력 부탁드립니다. (데이터: 주보_충청본부_센터 현황 > 신규상담 세부사항, 전일자 기준)"
    return msg


# ---------- 슬랙 전송 ----------
def send_to_slack(token: str, channel: str, text: str) -> None:
    body = json.dumps({"channel": channel, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        out = json.loads(res.read().decode("utf-8"))
    if not out.get("ok"):
        raise SystemExit(f"슬랙 전송 실패: {out.get('error')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsv", help="TSV 파일 경로 (지정 시 webhook 대신 사용)")
    ap.add_argument("--channel", default=TEST_CHANNEL)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = load_rows_from_tsv(args.tsv) if args.tsv else load_rows_from_webhook()
    print(f"데이터 {len(rows)}건 로드")

    msg = build_message(rows, date.today())
    if os.environ.get("GITHUB_ACTIONS"):
        # 공개 저장소 로그에 연락처가 남지 않도록 전문은 출력하지 않음
        print(f"메시지 생성 완료 ({len(msg)}자)")
    else:
        print("--- 메시지 미리보기 ---")
        print(msg)
        print("----------------------")

    if args.dry_run:
        print("(dry-run: 전송 안 함)")
        return

    token = _secret("SLACK_BOT_TOKEN", KEY_BOT_TOKEN)
    if not token:
        raise SystemExit("slack_bot_token 자격증명이 없습니다.")
    send_to_slack(token, args.channel, msg)
    print(f"전송 완료 → {args.channel}")


if __name__ == "__main__":
    main()
