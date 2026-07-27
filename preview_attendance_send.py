# -*- coding: utf-8 -*-
"""출석 현황 이미지 '레이아웃 미리보기'를 슬랙 테스트 채널로 발송.

케어포 수집 없이, 예시(더미) 데이터로 이미지를 생성해 지정 채널에 올린다.
'월평균 입소자' 열 확대 + 전월 평균 입소자 표시 레이아웃 확인용.
⚠️ 전월 값은 예시(가짜)다 — 실제 값 연결 전 레이아웃 확인 목적.

환경변수:
  SLACK_BOT_TOKEN   (필수) 봇 토큰
  PREVIEW_CHANNEL   (선택) 발송 채널 ID, 기본 C0BC37EB38C(테스트 방)
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.image_report import generate_image
from src import slack_notifier

# 회원님이 보여준 07-27 표 수치 + 전월은 예시(더미)
BRANCHES = [
    {"name": "둔산점",     "hyeon_won": 70, "gyeol_seok": 11, "chul_seok": 59, "capacity": 76,
     "avg_attendees": 57.17, "prev_avg_attendees": 55.00},
    {"name": "서구점",     "hyeon_won": 80, "gyeol_seok": 15, "chul_seok": 65, "capacity": 84,
     "avg_attendees": 60.43, "prev_avg_attendees": 58.90},
    {"name": "천안점",     "hyeon_won": 68, "gyeol_seok": 10, "chul_seok": 58, "capacity": 82,
     "avg_attendees": 46.70, "prev_avg_attendees": 49.20},
    {"name": "청주 오창점", "hyeon_won": 49, "gyeol_seok": 2,  "chul_seok": 47, "capacity": 62,
     "avg_attendees": 43.83, "prev_avg_attendees": 41.50},
]

COMMENT = ("🧪 *[테스트/미리보기]* 출석 현황 — '월평균 입소자' 열 확대 + *전월 평균 입소자* 표시안\n"
           "⚠️ 전월 값(괄호 안)은 *예시(더미)* 입니다. 레이아웃만 확인해 주세요. "
           "실제 전월값은 케어포 2-8 연결 후 반영됩니다.")


def main():
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise SystemExit("SLACK_BOT_TOKEN 환경변수가 없습니다.")
    channel = os.environ.get("PREVIEW_CHANNEL") or "C0BC37EB38C"
    img = generate_image(date.today(), BRANCHES)
    slack_notifier.send_image_via_api(
        token, channel, img,
        title="[미리보기] 지점별 출석 현황 — 전월 평균 입소자",
        mention_text=COMMENT,
    )
    print(f"미리보기 발송 완료 → {channel} ({len(img):,} bytes)")


if __name__ == "__main__":
    main()
