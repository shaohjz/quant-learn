@echo off
REM Finance Manager Agent runner (Windows Task Scheduler)
REM - Runs after market close (15:30) on trading days
REM - Generates daily finance manager report and pushes to WeChat Work

setlocal
set ROOT=C:\Users\Administrator\.openclaw\workspace\quant-learn
set PY=%ROOT%\.venv\Scripts\python.exe
set PYTHONPATH=%ROOT%

cd /d %ROOT%
if not exist output\finance_manager mkdir output\finance_manager

%PY% scripts\pm_finance_manager.py >> output\finance_manager\run.log 2>> output\finance_manager\run.err.log

endlocal
