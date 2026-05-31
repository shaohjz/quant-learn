@echo off
REM PM-Agent 每小时汇报 - Windows 计划任务版
REM 不占 OpenClaw cron 配额，由 schtasks 注册
REM 触发时间：9:00-18:00，每小时整点，周一至周五

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8
set PYTHONPATH=

REM 1. 超时保护 + 生成汇报 JSON
for /f "usebackq tokens=*" %%i in (`
  ".venv\Scripts\python.exe" -u -c "
import subprocess, json, sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
r = subprocess.run(
    [str(ROOT / '.venv' / 'Scripts' / 'python.exe'), 'scripts/pm_cli.py', 'report'],
    capture_output=True, text=True, cwd=str(ROOT), timeout=30
)
if r.returncode == 0:
    print(r.stdout.strip())
else:
    print('ERROR:' + r.stderr.strip()[:200])
"
`) do set REPORT_JSON=%%i

REM 2. 判断是否需要推送（有 stuck_tasks 或 pending_count > 15 或有新 commit）
echo %REPORT_JSON% | findstr /i "stuck_tasks" >nul 2>&1
if %errorlevel% == 0 (
    REM 有内容，调用 OpenClaw message tool 推送
    echo %REPORT_JSON% | ".venv\Scripts\python.exe" -u scripts\pm_agent_push.py
) else (
    echo NO_REPLY
)

pause
