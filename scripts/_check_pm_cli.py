import sqlite3, json, os, sys
sys.path.insert(0, r'C:\Users\Administrator\.openclaw\workspace\quant-learn')
# Try importing pm_cli logic or just call it as subprocess
# Actually let's just check the pm_cli.py to understand its interface
with open(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts\pm_cli.py') as f:
    content = f.read()
# Print first 50 lines to understand interface
lines = content.split('\n')
for i, l in enumerate(lines[:80]):
    print(f'{i+1}: {l}')
