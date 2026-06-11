@echo off
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8
set PYTHONPATH=
".venv\Scripts\python.exe" -u -m vqlearn.runners.run_paper_with_strategy --timeout 20400 --auto-trade 2>&1 | findstr /n "ERROR.*sim_executor.*未加载 OK.*Threshold.*strategy.*init.*start"
pause
