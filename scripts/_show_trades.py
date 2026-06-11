"""查看学习账户全部交易历史"""
import sqlite3
from datetime import datetime

conn = sqlite3.connect('data/sim_live_mirror.db')
conn.row_factory = sqlite3.Row

# 1. 表结构
print("=== 数据库表 ===")
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print(f"  {tables}")
print()

# 2. 学习账户(id=1)的全部交易记录
print("=" * 80)
print("📋 学习账户 (id=1) 交易历史")
print("=" * 80)

rows = conn.execute("""
    SELECT id, trade_date, stock_code, stock_name, direction, quantity, price, 
           amount, commission, tax, signal_reason, created_at
    FROM sim_trades WHERE account_id=1 ORDER BY created_at ASC
""").fetchall()

print(f"共 {len(rows)} 笔交易\n")
print(f"{'日期':<12} {'方向':^4} {'代码':<8} {'名称':<8} {'数量':>5} {'价格':>8} {'金额':>10} {'原因'}")
print("-" * 100)

total_buy = 0
total_sell = 0
for r in rows:
    d = dict(r)
    icon = "🟢买" if d['direction'] == 'BUY' else "🔴卖"
    reason = (d['signal_reason'] or '-')[:45]
    amount = d['amount'] or (d['quantity'] * d['price'])
    
    if d['direction'] == 'BUY':
        total_buy += amount
    else:
        total_sell += amount
    
    print(f"{d['trade_date']:<12} {icon:^4} {d['stock_code']:<8} {d['stock_name']:<8} "
          f"{d['quantity']:>5} {d['price']:>8.3f} ¥{amount:>9,.0f}  {reason}")

print("-" * 100)
print(f"累计买入: ¥{total_buy:,.0f} | 累计卖出: ¥{total_sell:,.0f} | 净投入: ¥{total_buy - total_sell:,.0f}")

# 3. 按股票汇总
print("\n" + "=" * 80)
print("📊 持仓变动汇总（按股票）")
print("=" * 80)

summary = conn.execute("""
    SELECT stock_code, stock_name,
           SUM(CASE WHEN direction='BUY' THEN quantity ELSE 0 END) as total_buy_qty,
           SUM(CASE WHEN direction='SELL' THEN quantity ELSE 0 END) as total_sell_qty,
           SUM(CASE WHEN direction='BUY' THEN amount ELSE 0 END) as total_buy_amt,
           SUM(CASE WHEN direction='SELL' THEN amount ELSE 0 END) as total_sell_amt,
           COUNT(*) as trade_count
    FROM sim_trades WHERE account_id=1
    GROUP BY stock_code
    ORDER BY total_buy_amt DESC
""").fetchall()

print(f"{'代码':<8} {'名称':<8} {'买入量':>6} {'卖出量':>6} {'净持仓':>6} {'买入额':>10} {'卖出额':>10} {'笔数':>4}")
print("-" * 80)
for r in summary:
    d = dict(r)
    net = (d['total_buy_qty'] or 0) - (d['total_sell_qty'] or 0)
    print(f"{d['stock_code']:<8} {d['stock_name']:<8} {d['total_buy_qty'] or 0:>6} "
          f"{d['total_sell_qty'] or 0:>6} {net:>6} "
          f"¥{d['total_buy_amt'] or 0:>9,.0f} ¥{d['total_sell_amt'] or 0:>9,.0f} {d['trade_count']:>4}")

conn.close()
