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

COMMENT = ("*#지점별 출석인원*\n"
           "안녕하세요 충청본부 입니다.\n"
           "각 지점별 출석 인원 공지 합니다.\n"
           "변동사항 있을 경우 스레드에 댓글로 남겨 주시기 바랍니다.\n"
           "*확인하신 지점은 이모지 남겨주세요!* ✅\n"
           "(케어포 1-1(수급중) / 6-4(시설일지) 확인 / 매일 10:40 기준 / 보류자 제외한 현 수급자 기준)\n"
           "──  🧪 문구 테스트 발송입니다(이미지 수치는 더미)  ──")


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
