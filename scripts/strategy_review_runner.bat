@echo off
REM strategy_review_runner.bat — 每日策略复盘（16:35，在 TradeJournal/DailyClose 之后）
REM schtasks: QuantLearn_StrategyReview
REM 依赖：16:15 TradeJournal + 16:20 DailyClose 已写完当日台账与净值

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8

".venv\Scripts\python.exe" -u scripts\strategy_review.py --write-spec --quiet >> output\strategy_review.log 2>&1
