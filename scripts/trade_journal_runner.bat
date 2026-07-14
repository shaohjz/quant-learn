@echo off
REM trade_journal_runner.bat — 每日交易台账（16:15，紧随 SwingDaily）
REM schtasks: QuantLearn_TradeJournal

cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set PYTHONIOENCODING=utf-8

".venv\Scripts\python.exe" -u scripts\trade_journal.py >> output\trade_journal.log 2>&1
