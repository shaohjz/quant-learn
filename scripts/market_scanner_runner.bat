@echo off
REM market_scanner_runner.bat - 7:50 周一-周五自动跑
REM 2026-05-25 起：复用 scanner_with_fallback（AKShare 不通时切 lite）
REM market_scanner.py 与 morning_scanner.py 都重度依赖 AKShare，二者降级方案相同

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn

echo ===== [%date% %time%] market scanner START ===== >> "output\market_scanner_runner.log"
".\.venv\Scripts\python.exe" -u "scripts\scanner_with_fallback.py" 1>> "output\market_scanner_runner.log" 2>>&1
echo ===== [%date% %time%] market scanner END   ===== >> "output\market_scanner_runner.log"

exit /b 0
