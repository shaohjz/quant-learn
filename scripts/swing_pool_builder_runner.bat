@echo off
REM 每日动态稳定波段池（方法过滤+软上限50）+ 盘前机会扫描推企微
REM 建议 schtasks：工作日 08:40（MorningScan 之后）
REM --mode auto：周末自动用日K历史；交易日用实时成交额

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8

echo ===== [%date% %time%] SwingPool build ===== >> output\swing_pool_builder.log
".venv\Scripts\python.exe" -u scripts\swing_pool_builder.py --max-pool 50 --min-score 70 --mode auto --force >> output\swing_pool_builder.log 2>&1
if errorlevel 1 (
  echo [ERR] swing_pool_builder failed >> output\swing_pool_builder.log
  exit /b 1
)

echo ===== [%date% %time%] Morning swing_auto notify ===== >> output\swing_pool_builder.log
".venv\Scripts\python.exe" -u scripts\swing_auto.py --title "盘前波段扫描报告" >> output\swing_pool_builder.log 2>&1
exit /b %ERRORLEVEL%
