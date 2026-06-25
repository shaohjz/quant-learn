#!/usr/bin/env python
"""
scripts/reset_account.py — 彻底重置模拟盘账户（force 模式，无交互）
"""
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, date
import yaml

ROOT = Path(__file__).resolve().parents[1]
SIM_DB = str(ROOT / "data" / "sim_live_mirror.db")
TODAY = date.today().strftime("%Y-%m-%d")
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# 从 config.yaml 读取正确的初始资金
cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
INITIAL_CASH = cfg.get("accounts", {}).get("learn", {}).get("initial_cash", 100000.0)

def reset_account():
    conn = sqlite3.connect(SIM_DB)
    cursor = conn.cursor()

    print(f"=== 重置模拟盘账户 ===")
    print(f"  初始资金（来自 config.yaml）: {INITIAL_CASH}")
    print(f"  日期: {TODAY}")

    # 1. 清空持仓
    cursor.execute("DELETE FROM sim_positions WHERE account_id=1")
    print(f"  ✅ 清空 sim_positions: {cursor.rowcount} 条")

    # 2. 清空交易记录
    cursor.execute("DELETE FROM sim_trades WHERE account_id=1")
    print(f"  ✅ 清空 sim_trades: {cursor.rowcount} 条")
    cursor.execute("DELETE FROM sim_orders WHERE account_id=1")
    print(f"  ✅ 清空 sim_orders: {cursor.rowcount} 条")
    cursor.execute("DELETE FROM sim_fills WHERE account_id=1")
    print(f"  ✅ 清空 sim_fills: {cursor.rowcount} 条")

    # 3. 清理老的 NAV
    cursor.execute("DELETE FROM sim_daily_nav WHERE account_id=1")
    print(f"  ✅ 清空 sim_daily_nav: {cursor.rowcount} 条")

    # 4. 插入新的 NAV 记录
    cursor.execute("""
        INSERT INTO sim_daily_nav 
        (account_id, trade_date, total_value, cash, market_value, 
         daily_return, cumulative_return, max_drawdown, created_at)
        VALUES (?, ?, ?, ?, 0, 0, 0, 0, ?)
    """, (1, TODAY, INITIAL_CASH, INITIAL_CASH, NOW))
    print(f"  ✅ 插入新 NAV: {TODAY}, total={INITIAL_CASH}")

    # 5. 重置账户
    cursor.execute("""
        UPDATE sim_account 
        SET cash = ?, total_value = ?, initial_cash = ?, updated_at = ?
        WHERE id = 1
    """, (INITIAL_CASH, INITIAL_CASH, INITIAL_CASH, NOW))
    print(f"  ✅ 重置账户: cash={INITIAL_CASH}, total_value={INITIAL_CASH}, initial_cash={INITIAL_CASH}")

    conn.commit()
    conn.close()
    print(f"\n✅ 重置完成！所有数据源已统一为 {INITIAL_CASH}")

if __name__ == "__main__":
    reset_account()
