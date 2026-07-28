@echo off
REM vqlearn_live_runner.bat - run vqlearn paper-strategy runner via venv python
REM Triggered by Windows Task Scheduler at 09:25 each trading day
REM Auto-stops at 15:05 via --timeout (5h40m = 20400 seconds)
REM 2026-05-21: 默认 --auto-trade off（先观察，明天再开）

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn

set PYTHONIOENCODING=utf-8
set PYTHONPATH=

REM Rotate log: keep only today's run, archive yesterday
if exist output\vqlearn_live.log (
    move /Y output\vqlearn_live.log output\vqlearn_live.prev.log >nul 2>&1
)

REM 5h40m = 20400s; runs 09:25 -> 15:05 inclusive
REM REQ-100: 只跑观察+shadow，不加 --auto-trade（避免与 Pulse/#3 双线吵）
".venv\Scripts\python.exe" -u -m vqlearn.runners.run_paper_with_strategy --timeout 20400 >> output\vqlearn_live.log 2>&1

exit /b %ERRORLEVEL%
