@echo off
REM 盘中统一脉搏：真仓阈值 + 波段机会 + 指数快检
REM 建议：工作日 09:35 起每 10 分钟，直到 14:50

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8

".venv\Scripts\python.exe" -u scripts\quant_pulse.py >> output\quant_pulse.log 2>&1
