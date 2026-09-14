@echo off
REM prod_clock_runner.bat — 3-windows 产机时钟（替代扫描类 schtasks）
REM OpenClaw systemEvent：工作日每 10 分钟
REM 禁止做成 LLM agentTurn

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8
set HOME=C:\Users\Administrator
set GIT_SSH_COMMAND=ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=C:/Users/Administrator/.ssh/known_hosts -i C:/Users/Administrator/.ssh/id_ed25519

if not exist output mkdir output

".venv\Scripts\python.exe" -u scripts\prod_clock.py >> output\prod_clock.log 2>&1
exit /b %ERRORLEVEL%
