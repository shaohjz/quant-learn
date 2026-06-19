@echo off
REM run_financial_manager_daily.bat - 每日 15:30 运行理财经理 Agent
REM 检查今日是否为交易日，如果是则运行 financial_manager_agent.py

python -c "from datetime import date; import sys; sys.exit(0 if date.today().weekday() < 5 else 1)" 2>nul
if errorlevel 1 (
    echo %date% %time% - 今日为非交易日，跳过运行
    exit /b 0
)

echo %date% %time% - 开始运行理财经理 Agent...
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
python scripts/financial_manager_agent.py

if errorlevel 1 (
    echo %date% %time% - 运行失败，请检查日志
    exit /b 1
) else (
    echo %date% %time% - 运行成功
    exit /b 0
)
