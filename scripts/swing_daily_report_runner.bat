@echo off
REM swing_daily_report_runner.bat — 波段交易日报（扫池 + 结论 + 持仓处置）
REM 建议 schtasks / OpenClaw systemEvent：每个交易日 16:05

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8

".venv\Scripts\python.exe" -u scripts\swing_daily_report.py >> output\swing_daily_report.log 2>&1
