@echo off
REM signal_ledger_runner.bat — 信号结果台账：记录当日信号 + 回填前瞻收益
REM schtasks：每个交易日 16:25（在 DailyClose 16:20 之后，记分卡 16:30 之前）

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8

".venv\Scripts\python.exe" -u scripts\signal_ledger.py >> output\signal_ledger.log 2>&1
