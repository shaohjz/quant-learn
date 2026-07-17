@echo off
REM 每日动态稳定波段池（优胜劣汰 Top20）
REM 建议 schtasks：工作日 08:40（MorningScan 之后）
REM --mode auto：周末自动用日K历史；交易日用实时成交额

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8

".venv\Scripts\python.exe" -u scripts\swing_pool_builder.py --top 20 --mode auto --force >> output\swing_pool_builder.log 2>&1
