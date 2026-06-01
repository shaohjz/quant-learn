@echo off
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
python scripts\review_missing_check.py >> logs\review_missing_runner.log 2>&1
