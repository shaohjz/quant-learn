@echo off
REM stop_loss_watch_runner.bat — REQ-048 止损巡检（直跑，不经 LLM）
REM 建议 Windows 计划任务：交易日 09:35-14:55 每 5 分钟

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8

".venv\Scripts\python.exe" -u scripts\stop_loss_auto_sell.py >> output\stop_loss_auto_sell.log 2>&1
