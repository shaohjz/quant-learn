@echo off
REM Daily review runner - calls daily_review.py at 9:00 every weekday morning
REM Reviews yesterday's trading.

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
".\.venv\Scripts\python.exe" "scripts\daily_review.py" 1>> "output\daily_review_runner.log" 2>>&1
exit /b 0
