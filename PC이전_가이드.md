# PC 이전 가이드 (케어포 자동화 전체: 출석보고·차량관리·지점점검·PWA)

새 PC에서 이 문서를 클로드 코드에게 보여주면 아래 단계를 대신 실행해 줍니다.

## 옮겨야 하는 것 (전체 목록)

| 항목 | 위치 (구 PC) | 이전 방법 |
|---|---|---|
| 코드 전체 (출석·차량·지점점검) | `바탕화면\클로드코드\carefor-auto` | 백업 폴더 복사 (git clone 도 가능) |
| 차량관리 PWA | `바탕화면\클로드코드\차량관리앱_PWA_완성` | 백업 폴더 복사 (git 아님 — 복사 필수) |
| 결과 엑셀 4개 | `바탕화면\클로드코드\*대조결과*.xlsx` | 백업 폴더에 포함 |
| 수급자 원본 데이터 | `carefor-auto\audit_results\*.json` | 백업 폴더에 포함 (개인정보 — git 에 없음) |
| 케어포/슬랙/시트 자격증명 6개 | Windows 자격증명 관리자 | `secrets.json` 으로 내보내기/복원 |
| 지점 설정 | `%LOCALAPPDATA%\carefor-auto\config.yaml` | 백업에 포함, import 가 복원 |
| 주간 점검 스케줄 | 작업 스케줄러 "케어포 지점점검 (매주 월 7시)" | XML 내보내기/등록 |
| 클로드 메모리 (작업 인수인계) | `C:\Users\alsgm\.claude\projects\...\memory` | 백업의 `claude_memory` 폴더 |

이전이 **필요 없는 것**: GitHub Actions 클라우드 자동화(출석보고, 주간 점검 요약)와 구글시트 — PC와 무관하게 계속 돌아감.

## 구 PC에서 (1단계)

```
cd C:\Users\alsgm\OneDrive\Desktop\클로드코드\carefor-auto
py -X utf8 tools\pc_migration_export.py
```
→ `바탕화면\케어포_PC이전백업` 폴더 생성됨. USB/외장하드/클라우드로 새 PC에 복사.

## 새 PC에서 (2단계)

1. **Python 설치** (python.org, 3.12 이상, "Add to PATH" 체크)
2. 백업 폴더의 `클로드코드` 폴더를 새 PC 바탕화면에 복사
3. 명령 프롬프트에서:
   ```
   cd %USERPROFILE%\Desktop\클로드코드\carefor-auto
   pip install -r requirements.txt openpyxl
   playwright install chromium
   py -X utf8 tools\pc_migration_import.py "백업폴더경로"
   ```
4. 작업 스케줄러 등록 (관리자 PowerShell):
   ```
   schtasks /create /tn "케어포 지점점검 (매주 월 7시)" /xml "백업폴더\scheduled_task_지점점검.xml"
   ```
   ※ XML 안의 실행 경로가 새 PC 사용자명과 다르면 수정 필요 (클로드에게 맡기면 됨)
5. **클로드 코드 설치** 후 `클로드코드` 폴더에서 실행 → 백업의 `claude_memory` 내용을
   새 메모리 폴더에 복사해 달라고 요청 (그러면 기존 작업 맥락 그대로 이어짐)
6. 동작 확인: `py -X utf8 run_audit.py --branch 천안점 --limit 2`
7. GitHub 푸시가 필요하면 git 로그인: `git push` 시 브라우저 인증 (min743 계정)
8. **백업 폴더의 secrets.json 삭제** (비밀번호 평문!)

## 주의

- 경로가 `C:\Users\alsgm\...` 으로 하드코딩된 파일이 일부 있음
  (`audit\make_extra_sheets.py`, `audit\merge_extra_inline.py`, `tools\pc_migration_export.py`).
  새 PC 사용자명이 다르면 수정 필요 — 새 PC의 클로드에게 "경로 하드코딩 수정해줘"라고 하면 됨.
- 구 PC의 .venv 는 복사 안 함 (새 PC에서는 시스템 파이썬으로 통일 — openpyxl 포함 설치했으므로 문제없음).
