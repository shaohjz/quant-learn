"""
scripts/sync_real_position.py — 真实账户持仓同步工具

用法（命令行）：
  # 买入
  python scripts/sync_real_position.py buy <code> <name> <qty> <price>

  # 卖出（部分卖：留下 qty=N；全卖：qty=0）
  python scripts/sync_real_position.py sell <code> <qty> <price>

  # 设置可用现金
  python scripts/sync_real_position.py set-cash <amount>

  # 查看当前持仓
  python scripts/sync_real_position.py list

例：
  python scripts/sync_real_position.py buy 002156 通富微电 100 55.30
  python scripts/sync_real_position.py sell 002453 0 6.50    # 全部卖出华软
  python scripts/sync_real_position.py sell 600330 200 30.00 # 卖 200 股，留 200
  python scripts/sync_real_position.py set-cash 9635.41
  python scripts/sync_real_position.py list

⚠️ 仅操作 sim_account.id=2 (real_portfolio)；不会动学习账户。
"""
from __future__ import annotations

import sys
import sqlite3
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data' / 'sim_live_mirror.db'
ACCOUNT_ID = 2  # 真实账户

# A 股费率（真实账户参考券商，简单用万 2.5 + 印花 0.05%）
COMMISSION_RATE = 0.00025
COMMISSION_MIN = 5.0
TAX_RATE = 0.0005
LOT_SIZE = 100


def conn_ro_rw():
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    return c


def get_account(c) -> dict | None:
    r = c.execute("SELECT * FROM sim_account WHERE id=?", (ACCOUNT_ID,)).fetchone()
    return dict(r) if r else None


def get_position(c, code: str) -> dict | None:
    r = c.execute(
        "SELECT * FROM sim_positions WHERE account_id=? AND stock_code=?",
        (ACCOUNT_ID, code)
    ).fetchone()
    return dict(r) if r else None


def insert_trade(c, code: str, name: str, direction: str, price: float, qty: int,
                 commission: float, tax: float, signal_reason: str):
    c.execute(
        """INSERT INTO sim_trades
           (account_id, trade_date, stock_code, stock_name, direction, price, quantity,
            amount, commission, tax, signal_reason, broker)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'real_portfolio')""",
        (ACCOUNT_ID, date.today().isoformat(), code, name, direction, price, qty,
         price * qty, commission, tax, signal_reason)
    )


def upsert_position(c, code: str, name: str, qty: int, avg_cost: float, cur_price: float):
    if qty <= 0:
        c.execute(
            "DELETE FROM sim_positions WHERE account_id=? AND stock_code=?",
            (ACCOUNT_ID, code)
        )
        return
    mv = qty * cur_price
    pnl = (cur_price - avg_cost) * qty
    pnl_pct = (cur_price / avg_cost - 1) * 100 if avg_cost > 0 else 0
    existing = c.execute(
        "SELECT id FROM sim_positions WHERE account_id=? AND stock_code=?",
        (ACCOUNT_ID, code)
    ).fetchone()
    if existing:
        c.execute(
            """UPDATE sim_positions SET stock_name=?, quantity=?, avg_cost=?, current_price=?,
               market_value=?, pnl=?, pnl_pct=?, updated_at=CURRENT_TIMESTAMP
               WHERE account_id=? AND stock_code=?""",
            (name, qty, avg_cost, cur_price, mv, pnl, pnl_pct, ACCOUNT_ID, code)
        )
    else:
        c.execute(
            """INSERT INTO sim_positions
               (account_id, stock_code, stock_name, quantity, avg_cost, current_price,
                market_value, pnl, pnl_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ACCOUNT_ID, code, name, qty, avg_cost, cur_price, mv, pnl, pnl_pct)
        )


def update_total_value(c):
    mv_row = c.execute(
        "SELECT COALESCE(SUM(market_value),0) AS s FROM sim_positions WHERE account_id=?",
        (ACCOUNT_ID,)
    ).fetchone()
    cash_row = c.execute("SELECT cash FROM sim_account WHERE id=?", (ACCOUNT_ID,)).fetchone()
    total = (mv_row['s'] or 0) + (cash_row['cash'] or 0)
    c.execute(
        "UPDATE sim_account SET total_value=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (total, ACCOUNT_ID)
    )


def cmd_buy(args):
    if len(args) < 4:
        print('用法: buy <code> <name> <qty> <price>')
        sys.exit(2)
    code, name = args[0], args[1]
    qty = int(args[2]); price = float(args[3])
    amount = qty * price
    commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
    total_cost = amount + commission

    c = conn_ro_rw()
    acc = get_account(c)
    if not acc:
        print('❌ 真实账户不存在')
        sys.exit(1)
    cash = acc['cash']
    if total_cost > cash + 0.01:
        ans = input(f'⚠️ 现金 {cash:.2f} < 需 {total_cost:.2f}，是否继续(此处仅记录)? [y/N] ')
        if ans.lower() != 'y':
            print('已取消'); sys.exit(0)

    # 计算新成本
    pos = get_position(c, code)
    if pos:
        new_qty = pos['quantity'] + qty
        new_avg = (pos['quantity'] * pos['avg_cost'] + amount + commission) / new_qty
    else:
        new_qty = qty
        new_avg = (amount + commission) / qty

    insert_trade(c, code, name, 'BUY', price, qty, commission, 0,
                 f'手动同步: 买入 {qty}股')
    c.execute("UPDATE sim_account SET cash=cash-?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
              (total_cost, ACCOUNT_ID))
    upsert_position(c, code, name, new_qty, new_avg, price)
    update_total_value(c)
    c.commit(); c.close()
    print(f'✅ 买入 {name} ({code}) {qty}股 @{price:.3f}, 含费 {total_cost:.2f}')
    print(f'   新成本 {new_avg:.3f}, 新数量 {new_qty}')


def cmd_sell(args):
    if len(args) < 3:
        print('用法: sell <code> <qty> <price>   (qty=0 表示全卖)')
        sys.exit(2)
    code = args[0]; qty_arg = int(args[1]); price = float(args[2])
    c = conn_ro_rw()
    pos = get_position(c, code)
    if not pos:
        print(f'❌ {code} 无持仓'); sys.exit(1)
    sell_qty = pos['quantity'] if qty_arg == 0 else qty_arg
    if sell_qty > pos['quantity']:
        print(f'❌ 卖 {sell_qty} 超过持仓 {pos["quantity"]}'); sys.exit(1)

    amount = sell_qty * price
    commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
    tax = amount * TAX_RATE
    net = amount - commission - tax

    insert_trade(c, code, pos['stock_name'], 'SELL', price, sell_qty, commission, tax,
                 f'手动同步: 卖出 {sell_qty}股')
    c.execute("UPDATE sim_account SET cash=cash+?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
              (net, ACCOUNT_ID))
    new_qty = pos['quantity'] - sell_qty
    upsert_position(c, code, pos['stock_name'], new_qty, pos['avg_cost'], price)
    update_total_value(c)
    c.commit(); c.close()
    print(f'✅ 卖出 {pos["stock_name"]} ({code}) {sell_qty}股 @{price:.3f}')
    print(f'   到手 {net:.2f}（佣金 {commission:.2f} + 印花 {tax:.2f}）')
    if new_qty == 0:
        print(f'   持仓已清空')
    else:
        print(f'   剩余 {new_qty} 股')


def cmd_set_cash(args):
    if len(args) < 1:
        print('用法: set-cash <amount>')
        sys.exit(2)
    amount = float(args[0])
    c = conn_ro_rw()
    c.execute("UPDATE sim_account SET cash=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
              (amount, ACCOUNT_ID))
    update_total_value(c)
    c.commit(); c.close()
    print(f'✅ 真实账户可用现金已设为 ¥{amount:,.2f}')


def cmd_list(_args):
    c = conn_ro_rw()
    acc = get_account(c)
    print(f"=== 真实账户 (id={ACCOUNT_ID} / {acc['account_name']}) ===")
    print(f"  现金 ¥{acc['cash']:,.2f}  总值 ¥{acc['total_value']:,.2f}")
    print(f"  更新时间: {acc['updated_at']}")
    rows = c.execute(
        "SELECT * FROM sim_positions WHERE account_id=? ORDER BY market_value DESC",
        (ACCOUNT_ID,)
    ).fetchall()
    if not rows:
        print('  (无持仓)')
    else:
        print(f"\n  {'代码':<8} {'名称':<8} {'数量':>6} {'成本':>8} {'现价':>8} {'市值':>10} {'盈亏':>10} {'%':>8}")
        for r in rows:
            print(f"  {r['stock_code']:<8} {r['stock_name']:<8} {r['quantity']:>6} "
                  f"{r['avg_cost']:>8.3f} {r['current_price']:>8.3f} "
                  f"{r['market_value']:>10.2f} {r['pnl']:>+10.2f} {r['pnl_pct']:>+7.2f}%")
    c.close()


COMMANDS = {
    'buy': cmd_buy,
    'sell': cmd_sell,
    'set-cash': cmd_set_cash,
    'list': cmd_list,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == '__main__':
    main()
