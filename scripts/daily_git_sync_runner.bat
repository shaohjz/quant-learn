@echo off
REM daily_git_sync_runner.bat - evening sync of trade journal / PM / QA / Ops / LLM reports to master
REM schtasks:
REM   QuantLearn_DailyGitSync         18:45  MON-FRI  (journal main shift)
REM   QuantLearn_DailyGitSyncEvening  20:30  MON-FRI  (pickup 20:00 LLM reports)
REM red lines: no trading-core code, no force push, no config.local

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8
REM fix: SYSTEM account has empty HOME and OpenSSH does not read admin .ssh,
REM causing "Host key verification failed" on push. Point SSH at admin key/known_hosts explicitly.
set HOME=C:\Users\Administrator
set GIT_SSH_COMMAND=ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=C:/Users/Administrator/.ssh/known_hosts -i C:/Users/Administrator/.ssh/id_ed25519

if not exist output mkdir output

".venv\Scripts\python.exe" -u scripts\daily_git_sync.py >> output\daily_git_sync.log 2>&1
exit /b %ERRORLEVEL%
