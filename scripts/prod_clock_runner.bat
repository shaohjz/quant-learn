@echo off
REM prod_clock_runner.bat — 3-windows 产机时钟（替代扫描类 schtasks）
REM OpenClaw systemEvent：工作日每 10 分钟
REM 禁止做成 LLM agentTurn

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8
set HOME=C:\Users\Administrator
set GIT_SSH_COMMAND=ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=C:/Users/Administrator/.ssh/known_hosts -i C:/Users/Administrator/.ssh/id_ed25519

if not exist output mkdir output

REM 注意：prod_clock.py 自己写 output\prod_clock.log，
REM 这里再用 >> 重定向到同一文件会因 cmd 持有句柄导致 Python 端 PermissionError，故不重定向。
".venv\Scripts\python.exe" -u scripts\prod_clock.py
exit /b %ERRORLEVEL%
