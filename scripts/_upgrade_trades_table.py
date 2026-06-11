"""
升级 sim_trades 表: 加 trade_context JSON 字段存完整决策上下文
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "sim_live_mirror.db"
conn = sqlite3.connect(str(DB))

# 检查是否已有 trade_context 列
cols = [r[1] for r in conn.execute("PRAGMA table_info(sim_trades)").fetchall()]
if 'trade_context' not in cols:
    conn.execute("ALTER TABLE sim_trades ADD COLUMN trade_context TEXT")
    print("✓ 添加 trade_context 列")
else:
    print("✓ trade_context 列已存在")

# 给现有记录补充 context（基于已有的 signal_reason）
rows = conn.execute("SELECT id, stock_code, direction, signal_reason FROM sim_trades WHERE trade_context IS NULL").fetchall()
import json
for row in rows:
    ctx = {
        'signal': row[3] or '未记录',
        'strategy': '阈值触发' if row[3] and '自动' in (row[3] or '') else '手动',
    }
    conn.execute("UPDATE sim_trades SET trade_context=? WHERE id=?", (json.dumps(ctx, ensure_ascii=False), row[0]))

conn.commit()
print(f"✓ 补充了 {len(rows)} 条历史记录的 context")

# 同时升级 signal_reason 字段：确保以后更详细
# 看看当前的 signal_reason 内容
print("\n=== 现有 signal_reason 示例 ===")
for r in conn.execute("SELECT stock_code, stock_name, direction, signal_reason FROM sim_trades ORDER BY created_at DESC LIMIT 5").fetchall():
    print(f"  {r[0]} {r[1]} {r[2]} | {r[3]}")

conn.close()
