import sqlite3
from datetime import datetime

# 清理测试数据
print("开始清理测试数据...")

# 1. 清理 sim_positions 中的测试数据
conn = sqlite3.connect('data/sim_live_mirror.db')
c = conn.cursor()

# 删除测试持仓
c.execute("DELETE FROM sim_positions WHERE stock_code IN ('000000', '000001', '000002') OR stock_name LIKE 'Test%'")
deleted_positions = c.rowcount
print(f"  删除测试持仓: {deleted_positions} 条")

# 删除相关的 sim_trades
c.execute("DELETE FROM sim_trades WHERE stock_code IN ('000000', '000001', '000002') OR stock_name LIKE 'Test%'")
deleted_trades = c.rowcount
print(f"  删除测试成交: {deleted_trades} 条")

# 删除相关的 threshold_state
c.execute("DELETE FROM threshold_state WHERE stock_code IN ('000000', '000001', '000002')")
deleted_thresholds = c.rowcount
print(f"  删除测试阈值状态: {deleted_thresholds} 条")

conn.commit()
conn.close()

print("\n✅ 测试数据清理完成")

# 2. 更新相关任务状态
conn = sqlite3.connect('data/pm.db')
c = conn.cursor()

now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# 更新 REQ-070
c.execute("UPDATE tasks SET status='fixed', updated_at=? WHERE id='REQ-070'", (now,))
print(f"\n更新 REQ-070: sim_positions 中存在测试脏数据 → fixed")

# 更新 TASK-20260705-0215-002
c.execute("UPDATE tasks SET status='fixed', updated_at=? WHERE id='TASK-20260705-0215-002'", (now,))
print(f"更新 TASK-20260705-0215-002: 测试股票污染实盘模拟数据 → fixed")

# 更新 TASK-20260705-2007-3ee7
c.execute("UPDATE tasks SET status='fixed', updated_at=? WHERE id='TASK-20260705-2007-3ee7'", (now,))
print(f"更新 TASK-20260705-2007-3ee7: 测试股票污染模拟盘真实持仓数据 → fixed")

conn.commit()
conn.close()

print("\n✅ 任务状态已更新")
