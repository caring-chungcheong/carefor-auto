"""
GitHub Actions에서 차량관리 보고를 슬랙으로 전송.
"""
import os, sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_cars import fetch_vehicle_data, build_vehicle_message
from slack_sdk import WebClient

token   = os.environ.get("SLACK_BOT_TOKEN")
channel = os.environ.get("SLACK_CHANNEL", "C087JL55TA6")

if not token:
    print("ERROR: SLACK_BOT_TOKEN 환경변수가 없습니다.")
    sys.exit(1)

today          = date.today()
branches_data  = fetch_vehicle_data()
msg            = build_vehicle_message(today, branches_data)

client = WebClient(token=token)
client.chat_postMessage(channel=channel, text=msg)
print("차량관리 보고 전송 완료")
