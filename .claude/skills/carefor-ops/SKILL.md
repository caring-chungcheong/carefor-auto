---
name: carefor-ops
description: 케어포(carefor-auto) 운영 런북 — 상담 공지, 출석보고, 지점점검, 차량관리, 케어포 대조 실행 방법과 주의사항. 상담시트/출석관리/차량관리/지점점검/슬랙 공지/케어포 관련 작업 시 사용.
---

# carefor-auto 운영 런북

작업 폴더: `C:\Users\alsgm\OneDrive\Desktop\클로드코드\carefor-auto` (공개 저장소 min743/carefor-auto — **개인정보 커밋 금지**)
파이썬: 시스템 `py -X utf8` 사용 (venv 없음, Playwright·openpyxl·keyring 전부 시스템에 설치됨)

## 주요 명령

| 작업 | 명령 |
|---|---|
| 상담 공지 발송 (엑셀 생성→드라이브 갱신→슬랙) | `py -X utf8 publish_excel.py` (--dry-run 가능) |
| 케어포 수급자 캐시 갱신 (4지점 로그인, ~3분) | `py -X utf8 carefor_phone_check.py` (--skip-download는 캐시 재사용) |
| 지점점검 | `py -X utf8 run_audit.py --branch 천안점 --limit 5` |
| 출석보고 상태 확인 | GitHub API로 daily_report.yml runs 조회 (PAT는 `git credential fill`) |

## 슬랙 (전부 Incoming Webhook — 봇 토큰 없음, 무료 플랜)

- keyring 서비스명 `carefor-auto`: `slack_webhook_url`(#차량관리=테스트방), `arongi_webhook_url`(아롱이 앱), `consult_notice_webhook_url`(상담 공지 채널 C087JL55TA6)
- 발송처 임시 변경: env `ARONGI_WEBHOOK_URL` 지정
- 메시지는 Block Kit (header+context+divider). **연락처는 슬랙 표시 금지(개인정보)** — 엑셀에만.

## 구글 연동

- 시트 데이터 읽기: Apps Script 웹앱 (keyring `consult_webhook_url`, `?ss=main|phone&sheet=시트명`)
- 드라이브 업로드: `publish_excel.py`의 google_token() — `~/.clasprc.json` OAuth 재사용 (drive.file)
- 드라이브 파일은 **고정 이름 덮어쓰기** → 링크 불변, anyone 뷰어 전용
- Apps Script 재배포: scratchpad deploy_webapp.py 패턴 (REST API 직접 — clasp는 Node 24에서 고장)

## 규칙·주의

- 상담 집계 기준: **2026년 5월~** (consult_report.CUTOFF_YM)
- 출석보고: daily_report.yml 3중 구조 (10:45 본발송 / 11:00 백업 gate / 외부호출 백업 / 실패 슬랙알림). **오전에 dry_run 돌리면 gate 오인 — 금지**
- 잘 돌아가는 발송 경로는 새 방식 검증 전 제거 금지 (2026-07-07 사고)
- 크롬 확장은 script.google.com / api.slack.com / accounts.google.com 접근 불가 → Start-Process로 열고 사용자에게 클릭 요청
- 케어포 자동 로그인: eform.caring.co.kr/carefor 포털 → `login2('<ctmnumb>')`, 지점 코드는 config.yaml (%LOCALAPPDATA%\carefor-auto\config.yaml)
- 상세 인수인계: carefor-auto/작업요약_인수인계.md
