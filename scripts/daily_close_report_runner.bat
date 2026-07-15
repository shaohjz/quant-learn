@echo off
REM 收盘双账户日报（建议 15:10 或并入 16:20；勿当波段结论）
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" -u scripts\daily_close_report.py >> output\daily_close_report.log 2>&1
