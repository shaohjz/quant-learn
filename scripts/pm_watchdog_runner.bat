@echo off
REM pm_watchdog_runner.bat - run pm_watchdog.py via system python
REM Triggered by Windows Task Scheduler every 5 minutes

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn

set PYTHONIOENCODING=utf-8
set PM_WATCHDOG_PYTHON=python

python -u scripts\pm_watchdog.py >> output\pm_watchdog_runner.log 2>&1

exit /b %ERRORLEVEL%
