@echo off
REM Market Scanner runner - 每天盘前 7:50 跑（数据源最稳的时段）
REM 周一-周五跑，周末不跑（schtasks 控制）

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PUSH=1
set TOP_N=15

echo ===== [%date% %time%] market scanner START ===== >> "output\market_scanner_runner.log"
".\.venv\Scripts\python.exe" "scripts\market_scanner.py" 1>> "output\market_scanner_runner.log" 2>>&1
echo ===== [%date% %time%] market scanner END   ===== >> "output\market_scanner_runner.log"

exit /b 0
