@echo off
REM strategy_scorecard_runner.bat — 每日策略记分卡（只读统计 + 漂移告警 + 企微一行结论）
REM schtasks：每个交易日 16:30（必须在 signal_ledger 16:25 之后）

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8

".venv\Scripts\python.exe" -u scripts\strategy_scorecard.py >> output\strategy_scorecard.log 2>&1
