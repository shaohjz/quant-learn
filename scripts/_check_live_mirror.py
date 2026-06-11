"""检查 live_mirror 当前状态 + 电信走势"""
import sqlite3
from pathlib import Path

DB = Path(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db')

conn = sqlite3.connect(DB)
cur = conn.cursor()

# 探测 schema
print('=== tables ===')
for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    print(row[0])

print('\n=== sim_account schema ===')
for row in cur.execute("PRAGMA table_info(sim_account)"):
    print(row)

print('\n=== sim_account rows ===')
for row in cur.execute("SELECT * FROM sim_account"):
    print(row)

print('\n=== sim_positions schema ===')
for row in cur.execute("PRAGMA table_info(sim_positions)"):
    print(row)

print('\n=== sim_positions rows ===')
for row in cur.execute("SELECT account_id, stock_code, stock_name, quantity, avg_cost, current_price, pnl_pct FROM sim_positions WHERE quantity>0 ORDER BY account_id, stock_code"):
    print(row)

print('\n=== sim_trades schema ===')
for row in cur.execute("PRAGMA table_info(sim_trades)"):
    print(row)

print('\n=== sim_trades 中国电信 last 10 ===')
for row in cur.execute("SELECT * FROM sim_trades WHERE stock_code='601728' ORDER BY rowid DESC LIMIT 10"):
    print(row)

conn.close()
