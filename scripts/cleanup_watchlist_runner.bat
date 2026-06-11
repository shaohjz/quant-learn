@echo off
REM scripts/cleanup_watchlist_runner.bat — 观察池淘汰器启动脚本
REM 用于 Windows 计划任务

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
.venv\Scripts\python.exe -u scripts\cleanup_watchlist.py >> output\cleanup_watchlist.log 2>&1
