import sqlite3
from datetime import datetime, date
import json

db = 'data/sim_live_mirror.db'
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=" * 60)
print("模拟盘账户状态")
print("=" * 60)
cur.execute("SELECT * FROM sim_account")
accounts = cur.fetchall()
for acc in accounts:
    print(f"账户: {acc['account_name']} (id={acc['id']})")
    print(f"  初始资金: {acc['initial_cash']:.2f}")
    print(f"  可用资金: {acc['cash']:.2f}")
    print(f"  总市值: {acc['total_value']:.2f}")
    print(f"  更新时间: {acc['updated_at']}")
    print()

print("=" * 60)
print("当前持仓")
print("=" * 60)
cur.execute("""
    SELECT sp.*, sa.account_name 
    FROM sim_positions sp 
    JOIN sim_account sa ON sp.account_id = sa.id
    ORDER BY sp.account_id, sp.stock_code
""")
positions = cur.fetchall()
total_market_value = 0
total_pnl = 0
for pos in positions:
    mkt_val = pos['market_value']
    pnl = pos['pnl']
    total_market_value += mkt_val
    total_pnl += pnl
    print(f"[{pos['account_name']}] {pos['stock_name']}({pos['stock_code']})")
    print(f"  持仓: {pos['quantity']}股, 成本: {pos['avg_cost']:.2f}, 现价: {pos['current_price']:.2f}")
    print(f"  市值: {mkt_val:.2f}, 盈亏: {pnl:.2f} ({pos['pnl_pct']:.2f}%)")
    if pos['trailing_stop_price']:
        print(f"  移动止损价: {pos['trailing_stop_price']:.2f}")
    print()

print(f"持仓总市值: {total_market_value:.2f}")
print(f"持仓总盈亏: {total_pnl:.2f}")
print()

print("=" * 60)
print("历史交易记录（最近10笔）")
print("=" * 60)
cur.execute("""
    SELECT st.*, sa.account_name 
    FROM sim_trades st
    JOIN sim_account sa ON st.account_id = sa.id
    ORDER BY st.trade_date DESC, st.id DESC
    LIMIT 10
""")
trades = cur.fetchall()
for t in trades:
    print(f"[{t['account_name']}] {t['trade_date']} {t['direction']} {t['stock_name']}({t['stock_code']})")
    print(f"  价格: {t['price']:.2f}, 数量: {t['quantity']}, 金额: {t['amount']:.2f}")
    print(f"  信号: {t['signal_reason']}")
    print()

print("=" * 60)
print("每日净值（最近10条）")
print("=" * 60)
cur.execute("""
    SELECT sd.*, sa.account_name 
    FROM sim_daily_nav sd
    JOIN sim_account sa ON sd.account_id = sa.id
    ORDER BY sd.trade_date DESC
    LIMIT 10
""")
navs = cur.fetchall()
for n in navs:
    print(f"[{n['account_name']}] {n['trade_date']}")
    print(f"  总市值: {n['total_value']:.2f}, 现金: {n['cash']:.2f}, 市值: {n['market_value']:.2f}")
    print(f"  日收益: {n['daily_return']:.4f}, 累计收益: {n['cumulative_return']:.4f}")
    if n['cash_jump_detected']:
        print(f"  ⚠️ 现金跳变: {n['cash_jump_reason']}")
    print()

print("=" * 60)
print("阈值状态（未关闭）")
print("=" * 60)
cur.execute("SELECT * FROM threshold_state WHERE status != 'closed' ORDER BY stock_code, rule_name")
thresholds = cur.fetchall()
for th in thresholds:
    print(f"{th['stock_code']} {th['rule_name']}: status={th['status']}, threshold={th['rule_threshold']}")
    if th['first_hit_date']:
        print(f"  首次触发: {th['first_hit_date']} @ {th['first_hit_price']}")
    print()

print("=" * 60)
print("持仓入场快照")
print("=" * 60)
cur.execute("""
    SELECT p.*, sa.account_name 
    FROM position_entry_snapshots p
    JOIN sim_account sa ON p.account_id = sa.id
    WHERE p.status = 'open'
    ORDER BY p.account_id, p.stock_code
""")
snapshots = cur.fetchall()
for s in snapshots:
    print(f"[{s['account_name']}] {s['stock_name']}({s['stock_code']})")
    print(f"  入场价: {s['entry_price']:.2f}, 当前价: {s['current_price']:.2f}")
    print(f"  浮动盈亏: {s['floating_pnl']:.2f} ({s['floating_pnl_pct']:.2f}%)")
    print(f"  策略标签: {s['strategy_tag']}")
    print()

conn.close()
