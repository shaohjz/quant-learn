@echo off
REM bank_swing_daily_runner.bat — 银行股专用波段结论（账户 #4）
REM 建议 schtasks：交易日 16:08（紧接 QuantLearn_SwingDaily 16:05）

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8

".venv\Scripts\python.exe" -u scripts\bank_swing_daily.py >> output\bank_swing_daily_report.log 2>&1
