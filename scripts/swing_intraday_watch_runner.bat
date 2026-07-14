@echo off
REM 盘中波段盯盘：机会买价 / 持仓止盈止损 → 企微
REM 建议 schtasks：工作日 09:35 起，每 10 分钟一次，至 14:50

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8

".venv\Scripts\python.exe" -u scripts\swing_intraday_watch.py >> output\swing_intraday_watch.log 2>&1
