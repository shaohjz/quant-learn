"""生成模拟的历史快照数据用于测试"""
import sqlite3
from pathlib import Path
from datetime import date, timedelta
import random

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sim_live_mirror.db"

# 生成过去30天的模拟数据
conn = sqlite3.connect(str(DB_PATH))

initial_asset = 100000
current_asset = initial_asset

for i in range(30, 0, -1):
    snapshot_date = (date.today() - timedelta(days=i)).isoformat()
    
    # 模拟每日资产波动 (-1% ~ +2%)
    daily_change = random.uniform(-0.01, 0.02)
    current_asset = current_asset * (1 + daily_change)
    
    # 模拟持仓数
    position_count = random.randint(3, 6)
    
    # 现金比例 10-30%
    cash_ratio = random.uniform(0.1, 0.3)
    cash = current_asset * cash_ratio
    market_value = current_asset - cash
    
    conn.execute("""
        INSERT OR REPLACE INTO daily_snapshot (
            snapshot_date, account_type, total_asset, 
            total_market_value, cash, position_count
        ) VALUES (?, 'sim', ?, ?, ?, ?)
    """, (snapshot_date, current_asset, market_value, cash, position_count))
    
    print(f"{snapshot_date}: ¥{current_asset:.2f} ({((current_asset - initial_asset) / initial_asset * 100):+.2f}%)")

conn.commit()
conn.close()

print("\n✅ 已生成30天模拟数据")
