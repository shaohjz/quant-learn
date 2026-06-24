@echo off
REM ops_daily_check_runner.bat - run ops_daily_check.py via system python
REM Triggered by Windows Task Scheduler daily at 8:00

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn

set PYTHONIOENCODING=utf-8

python -u scripts\ops_daily_check.py >> output\ops_daily_check_runner.log 2>&1

exit /b %ERRORLEVEL%
