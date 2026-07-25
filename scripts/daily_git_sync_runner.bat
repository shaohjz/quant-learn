@echo off
REM daily_git_sync_runner.bat — 晚间把交易台账 / PM / QA / Ops / LLM日报 落盘推到 master
REM schtasks 建议:
REM   QuantLearn_DailyGitSync         18:45  MON-FRI  （台账主班）
REM   QuantLearn_DailyGitSyncEvening  20:30  MON-FRI  （承接 20:00 LLM 各类日报）
REM 红线: 不推交易核心代码、不 force push、不碰 config.local

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8

if not exist output mkdir output

".venv\Scripts\python.exe" -u scripts\daily_git_sync.py >> output\daily_git_sync.log 2>&1
exit /b %ERRORLEVEL%
