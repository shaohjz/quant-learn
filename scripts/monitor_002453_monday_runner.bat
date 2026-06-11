@echo off
REM monitor_002453_monday_runner.bat - 周一开盘华软监控
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn

".venv\Scripts\python.exe" -u scripts\monitor_002453_monday.py >> output\monitor_002453.log 2>&1

exit /b %ERRORLEVEL%
