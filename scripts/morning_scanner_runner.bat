@echo off
REM morning_scanner_runner.bat - run morning_scanner.py via venv python
REM Triggered by Windows Task Scheduler at 08:30 on weekdays.

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn

".venv\Scripts\python.exe" -u scripts\morning_scanner.py --top 10 >> output\morning_scanner.log 2>&1

exit /b %ERRORLEVEL%
