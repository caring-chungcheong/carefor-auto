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

# 07-27 실제 수치(현월) + 케어포 2-8에서 뽑은 실제 전월 최종 평균(서구 59.92 검증 완료)
BRANCHES = [
    {"name": "둔산점",     "hyeon_won": 70, "gyeol_seok": 11, "chul_seok": 59, "capacity": 76,
     "avg_attendees": 57.17, "prev_avg_attendees": 57.69},
    {"name": "서구점",     "hyeon_won": 80, "gyeol_seok": 15, "chul_seok": 65, "capacity": 84,
     "avg_attendees": 60.43, "prev_avg_attendees": 59.92},
    {"name": "천안점",     "hyeon_won": 68, "gyeol_seok": 10, "chul_seok": 58, "capacity": 82,
     "avg_attendees": 46.70, "prev_avg_attendees": 45.27},
    {"name": "청주 오창점", "hyeon_won": 49, "gyeol_seok": 2,  "chul_seok": 47, "capacity": 62,
     "avg_attendees": 43.83, "prev_avg_attendees": 43.54},
]

COMMENT = ("🧪 *[테스트]* 출석 현황 — '월평균 입소자' 열 확대 + *전월 평균 입소자*(괄호, 회색) 표시안\n"
           "전월값은 케어포 2-8 실제 최종 평균입니다(서구 6월 59.92 검증 완료). 레이아웃·수치 확인 부탁드립니다.")


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
