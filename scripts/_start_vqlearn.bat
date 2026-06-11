@echo off
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONPATH=
set PYTHONIOENCODING=utf-8
call .venv\Scripts\python.exe -u -m vqlearn.runners.run_paper_with_strategy --timeout 20400 --auto-trade
pause
