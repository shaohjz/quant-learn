import sqlite3, os, sys
sys.path.insert(0, r'C:\Users\Administrator\.openclaw\workspace\quant-learn')

# live_mirror 模拟账户
db = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db'
print(f'DB exists: {os.path.exists(db)}')
conn = sqlite3.connect(db)
cur = conn.cursor()

# 看一下表结构
cur.execute("PRAGMA table_info(sim_trades)")
print('\n=== sim_trades schema ===')
for r in cur.fetchall():
    print(r)

# 今日交易
print('\n=== 今日 (2026-05-19) sim 交易 ===')
cur.execute("SELECT * FROM sim_trades WHERE trade_date='2026-05-19' ORDER BY id")
rows = cur.fetchall()
print(f'数量: {len(rows)}')
for r in rows:
    print(r)

# 全部交易
print('\n=== 全部 sim 交易 ===')
cur.execute("SELECT * FROM sim_trades ORDER BY id")
all_rows = cur.fetchall()
print(f'数量: {len(all_rows)}')
for r in all_rows:
    print(r)

# 今日推送过的阈值
print('\n=== 今日触发的阈值（alert_state.json） ===')
import json
state = json.load(open(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\output\alert_state.json', encoding='utf-8'))
today = state.get('2026-05-19', {})
for k, v in today.items():
    print(f'  {k}: {v}')

conn.close()
