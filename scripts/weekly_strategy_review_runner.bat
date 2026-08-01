@echo off
REM weekly_strategy_review_runner.bat — 每周策略复盘：研究链 → 参数提案 → 护栏采纳
REM schtasks：周五 17:00（台账/记分卡已就绪，早于 18:45 DailyGitSync 好把产物推走）
REM 注意：默认 strategy_feedback.auto_apply.enabled=false，本任务只出提案不改参数。

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8

".venv\Scripts\python.exe" -u scripts\weekly_strategy_review.py >> output\weekly_strategy_review.log 2>&1
