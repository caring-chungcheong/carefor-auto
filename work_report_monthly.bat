@echo off
REM Monthly: staff work-journal check (carefor 8-4) -> local report for the control tower.
REM ASCII ONLY. Korean paths break under cmd cp949 (pushd fails, task exits 255).
REM Output goes to Desktop\klaudecode\geunmuiljijeomgeom via audit/deskpath.py (Korean handled in Python).
REM Runs on the 1st of each month, AFTER CareforDailyPull (09:30) finishes. Carefor allows ONE login at a time.
setlocal
pushd "%~dp0"
py -X utf8 -m audit.collect_work_report --all --ym prev
set RC=%ERRORLEVEL%
if not "%RC%"=="0" goto :end
py -X utf8 -m audit.make_work_report_check --ym prev
set RC=%ERRORLEVEL%
:end
popd
endlocal & exit /b %RC%
