@echo off
REM Monthly review runner - 每月最后一个工作日 15:40 跑（用 schtasks 控制）

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PUSH=1

echo ===== [%date% %time%] monthly review START ===== >> "output\monthly_review_runner.log"
".\.venv\Scripts\python.exe" "scripts\monthly_review.py" 1>> "output\monthly_review_runner.log" 2>>&1
echo ===== [%date% %time%] monthly review END   ===== >> "output\monthly_review_runner.log"

exit /b 0
