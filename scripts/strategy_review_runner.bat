@echo off
REM strategy_review_runner.bat — 每日策略复盘（16:35，在 TradeJournal/DailyClose 之后）
REM schtasks: QuantLearn_StrategyReview
REM 依赖：16:15 TradeJournal + 16:20 DailyClose 已写完当日台账与净值

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8

echo ===== [%date% %time%] StrategyReview ===== >> output\strategy_review.log
".venv\Scripts\python.exe" -u scripts\strategy_review.py --write-spec --quiet >> output\strategy_review.log 2>&1
if errorlevel 1 (
  REM 不吞退出码：schtasks 的 Last Result 非 0 是守夜唯一能看到的信号。
  REM 2026-08-03~05 这条链断了三天没人发现，就是因为失败被日志吃掉了。
  echo [ERR] strategy_review failed errorlevel=%errorlevel% >> output\strategy_review.log
  exit /b 1
)
