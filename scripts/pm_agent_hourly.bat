@echo off
REM PM-Agent local runner (Windows Task Scheduler)
REM - Does NOT use OpenClaw cron quota
REM - Sends summary via the single webhook configured in config.local.yaml

setlocal
set ROOT=C:\Users\Administrator\.openclaw\workspace\quant-learn
set PY=%ROOT%\.venv\Scripts\python.exe
set PYTHONPATH=%ROOT%

cd /d %ROOT%
if not exist output mkdir output

%PY% scripts\pm_cli.py report --hours 1 > output\pm_agent_report.json 2>> output\pm_agent_hourly.err.log
if errorlevel 1 goto :EOF

%PY% scripts\pm_agent_push.py < output\pm_agent_report.json >> output\pm_agent_hourly.log 2>> output\pm_agent_hourly.err.log

endlocal
