@echo off
REM morning_scanner_runner.bat - 8:30 周一-周五自动跑
REM 2026-05-25 起：走 fallback 入口（主路径 morning_scanner，挂了切 scanner_lite）
REM 背景：AKShare 在云桌面被东财限流，主路径会卡死

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn

".venv\Scripts\python.exe" -u scripts\scanner_with_fallback.py >> output\morning_scanner.log 2>&1

exit /b %ERRORLEVEL%
