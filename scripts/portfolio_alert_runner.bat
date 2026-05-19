@echo off
REM portfolio_alert_runner.bat - run portfolio_alert.py via venv python
REM Triggered by Windows Task Scheduler. Script handles webhook push itself.

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn

".venv\Scripts\python.exe" -u scripts\portfolio_alert.py >> output\runner.log 2>&1

exit /b %ERRORLEVEL%
