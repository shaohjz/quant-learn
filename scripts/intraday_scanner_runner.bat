@echo off
REM scripts/intraday_scanner_runner.bat — 盘中异动扫描器启动脚本
REM 用于 Windows 计划任务

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
.venv\Scripts\python.exe -u scripts\intraday_scanner.py >> output\intraday_scanner.log 2>&1
