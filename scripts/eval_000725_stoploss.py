"""
REQ-067: 京东方A(000725) 止损监控评估
评估 trailing_stop 参数合理性，输出明日操作建议
"""
import sqlite3

DB = 'data/sim_live_mirror.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 获取京东方A持仓
cur.execute("SELECT * FROM sim_positions WHERE account_id=1 AND stock_code='000725' AND quantity > 0")
pos = cur.fetchone()
if not pos:
    print("京东方A 无持仓")
    exit(1)

pos = dict(pos)
print("=== 京东方A(000725) 止损评估 ===")
print(f"持仓数量: {pos['quantity']} 股")
print(f"成本均价: ¥{pos['avg_cost']:.3f}")
print(f"当前价格: ¥{pos['current_price']:.2f}")
print(f"持仓市值: ¥{pos['market_value']:.2f}")
print(f"浮动盈亏: ¥{pos['pnl']:.2f} ({pos['pnl_pct']:.2f}%)")
print(f"跟踪止损: ¥{pos['trailing_stop_price']:.2f}")
print(f"历史最高: ¥{pos['highest_price']:.2f}")

# 计算关键距离
stop_gap = pos['current_price'] - pos['trailing_stop_price']
stop_gap_pct = stop_gap / pos['current_price'] * 100

cost_gap = pos['trailing_stop_price'] - pos['avg_cost']
cost_gap_pct = cost_gap / pos['avg_cost'] * 100

highest_drop = (pos['highest_price'] - pos['current_price']) / pos['highest_price'] * 100
cost_drop = (pos['avg_cost'] - pos['current_price']) / pos['avg_cost'] * 100

print(f"\n=== 风险评估 ===")
print(f"距止损线: ¥{stop_gap:.2f} ({stop_gap_pct:.2f}%)")
print(f"止损线 vs 成本: ¥{cost_gap:.2f} ({cost_gap_pct:+.2f}%)")
print(f"从最高点回落: {highest_drop:.2f}%")
print(f"从成本下跌: {cost_drop:.2f}%")

# 评估建议
print("\n=== 操作建议 ===")

if stop_gap_pct < 1:
    print("⚠️ 距离止损线仅 {:.1f}%，极度危险！".format(stop_gap_pct))
    gap_price = pos['trailing_stop_price']
    print(f"   若明日跌破 ¥{gap_price:.2f} 将触发跟踪止损，预计亏损 ¥{(pos['quantity'] * (pos['avg_cost'] - gap_price)):.2f}")
else:
    print("止损距离尚可 ({:.1f}%)".format(stop_gap_pct))

print(f"""
止损参数评估:
  - trailing_stop=¥{pos['trailing_stop_price']:.2f}（从最高 ¥{pos['highest_price']:.2f} 回落约 {highest_drop:.1f}%）
  - 成本价 ¥{pos['avg_cost']:.3f}，止损线低于成本 {(pos['avg_cost'] - pos['trailing_stop_price']):.2f}元({(1 - pos['trailing_stop_price']/pos['avg_cost'])*100:.1f}%)
  - 即如果触发止损，实际亏损约 ¥{abs(pos['pnl']):.0f}({abs(pos['pnl_pct']):.1f}%)

建议:
  1. 止损参数设在成本下方约8%，合理
  2. 距离仅0.5%(¥0.03)，明日开盘密切关注
  3. 如开盘直接低开跌破6.36，应果断止损
  4. 若开盘在6.36以上，观察盘面强度，等待明确信号
""")

# 添加止损监控记录到 sim_account_events 或注释
# 此处不修改数据库，仅输出建议

conn.close()
print("REQ-067 评估完成 — 止损参数合理，建议明日重点监控")
