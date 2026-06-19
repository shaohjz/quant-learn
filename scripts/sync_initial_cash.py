#!/usr/bin/env python3
"""同步 sim_live_mirror.db 的 initial_cash 使其与 config.yaml 一致"""
import sys
sys.path.insert(0, r'C:\Users\Administrator\.openclaw\workspace\quant-learn')

import os
os.environ['QUANT_DB_PATH'] = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db'

from sim.config import get_account_config
from sim.db import get_conn, record_account_event

# 读取 config 中的 initial_cash
acct_cfg = get_account_config(1)
cfg_initial_cash = float(acct_cfg.get("initial_cash", 100000.0))
print(f'config initial_cash: {cfg_initial_cash}')

# 读取 DB 当前值
conn = get_conn()
c = conn.cursor()
c.execute("SELECT initial_cash, cash, total_value FROM sim_account WHERE id=1")
row = c.fetchone()
db_initial_cash = float(row["initial_cash"])
print(f'DB initial_cash (before): {db_initial_cash}')

if abs(db_initial_cash - cfg_initial_cash) < 0.01:
    print('Already consistent, no action needed')
else:
    # 记录事件
    record_account_event(
        account_id=1,
        event_type="config_sync",
        event_date="2026-06-19",
        old_initial_cash=db_initial_cash,
        new_initial_cash=cfg_initial_cash,
        reason=f"自动同步: DB.initial_cash={db_initial_cash} -> config.initial_cash={cfg_initial_cash}"
    )
    # 更新 DB
    c.execute(
        "UPDATE sim_account SET initial_cash=?, updated_at=datetime('now') WHERE id=1",
        (cfg_initial_cash,)
    )
    conn.commit()
    print(f'Updated initial_cash: {db_initial_cash} -> {cfg_initial_cash}')
    
    # 验证
    c.execute("SELECT initial_cash FROM sim_account WHERE id=1")
    print(f'DB initial_cash (after): {c.fetchone()["initial_cash"]}')

conn.close()
print('Done')
