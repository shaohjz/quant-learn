@echo off
REM Weekly review runner - 每周五 15:35 跑

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PUSH=1

echo ===== [%date% %time%] weekly review START ===== >> "output\weekly_review_runner.log"
".\.venv\Scripts\python.exe" "scripts\weekly_review.py" 1>> "output\weekly_review_runner.log" 2>>&1
echo ===== [%date% %time%] weekly review END   ===== >> "output\weekly_review_runner.log"

exit /b 0
