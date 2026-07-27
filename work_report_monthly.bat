@echo off
REM Monthly: staff work-journal check (carefor 8-4) -> local report for the control tower.
REM ASCII ONLY. Korean paths break under cmd cp949 (pushd fails, task exits 255).
REM Output goes to Desktop\klaudecode\geunmuiljijeomgeom via audit/deskpath.py (Korean handled in Python).
REM Runs on the 1st of each month, AFTER CareforDailyPull (09:30) finishes. Carefor allows ONE login at a time.
REM
REM Two passes on purpose:
REM   [1] previous month only (~2 min)  -> monthly snapshot, kept per month (history piles up)
REM   [2] since branch opening (~15 min) -> cumulative report the control tower links to
setlocal
pushd "%~dp0"

echo [1/2] previous month
py -X utf8 -m audit.collect_work_report --all --ym prev
set RC=%ERRORLEVEL%
if not "%RC%"=="0" goto :end
py -X utf8 -m audit.make_work_report_check --ym prev
set RC=%ERRORLEVEL%
if not "%RC%"=="0" goto :end

echo [2/2] since opening (cumulative)
py -X utf8 -m audit.collect_work_report --all
set RC=%ERRORLEVEL%
if not "%RC%"=="0" goto :end
py -X utf8 -m audit.make_work_report_check
set RC=%ERRORLEVEL%

:end
popd
endlocal & exit /b %RC%
