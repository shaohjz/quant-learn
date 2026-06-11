@echo off
REM Daily review runner - 每天 15:30 跑（盘后），双账户复盘 + 推送企微

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PUSH=1

echo ===== [%date% %time%] daily review START ===== >> "output\daily_review_runner.log"
".\.venv\Scripts\python.exe" "scripts\daily_review.py" 1>> "output\daily_review_runner.log" 2>>&1

echo ===== [%date% %time%] next watchlist START ===== >> "output\daily_review_runner.log"
".\.venv\Scripts\python.exe" "scripts\generate_next_watchlist.py" --push 1>> "output\daily_review_runner.log" 2>>&1
echo ===== [%date% %time%] next watchlist END   ===== >> "output\daily_review_runner.log"

echo ===== [%date% %time%] daily review END   ===== >> "output\daily_review_runner.log"

exit /b 0
