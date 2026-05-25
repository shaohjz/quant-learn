@echo off
REM 每天 18:30 自动执行 PM 流程，用于根据 test_reports 进行状态扭转及生成框架
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
".\.venv\Scripts\python.exe" "scripts\pm_daily_workflow.py" >> "pm\daily\workflow_cron.log" 2>&1
exit /b 0
