@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -X utf8 "지점점검_테스트.py"
pause
