@echo off
REM Finance Manager Agent runner (Windows Task Scheduler)
REM - Runs after market close (15:35) on trading days
REM - Writes daily_reports/YYYY-MM-DD-finance-report.md (Git whitelist) + output/finance_manager/
REM - Pushes summary to WeChat Work

setlocal
set ROOT=C:\Users\Administrator\.openclaw\workspace\quant-learn
set PY=%ROOT%\.venv\Scripts\python.exe
set PYTHONPATH=%ROOT%
set DRY_RUN=1

cd /d %ROOT%
if not exist output\finance_manager mkdir output\finance_manager
if not exist daily_reports mkdir daily_reports

REM DRY_RUN=1：只写报告、不自动建 PM 需求（赚钱闸优先，防噪音需求刷屏）
%PY% -u scripts\pm_finance_manager.py >> output\finance_manager\run.log 2>> output\finance_manager\run.err.log

endlocal
