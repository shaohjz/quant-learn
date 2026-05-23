"""周末账户健康总览：双账户余额 + 持仓 + 近 7 天交易"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "sim_live_mirror.db"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

print("=" * 64)
print(f"账户健康检查  DB: {DB}")
print("=" * 64)

print("\n[ sim_account ]")
for r in cur.execute(
    "SELECT id, account_name, initial_cash, cash, total_value, updated_at FROM sim_account ORDER BY id"
):
    print(
        f"  id={r['id']}  {r['account_name']:<16}  init={r['initial_cash']:>10.2f}  "
        f"cash={r['cash']:>10.2f}  total={r['total_value']:>10.2f}  upd={r['updated_at']}"
    )

print("\n[ sim_positions ]")
for r in cur.execute(
    "SELECT account_id, stock_code, stock_name, quantity, avg_cost, current_price, pnl_pct "
    "FROM sim_positions ORDER BY account_id, stock_code"
):
    print(
        f"  acct={r['account_id']}  {r['stock_code']} {r['stock_name'] or '':<10}  "
        f"qty={r['quantity']:>4}  avg={r['avg_cost']:.3f}  cur={r['current_price'] or 0:.3f}  "
        f"pnl%={r['pnl_pct'] or 0:+.2f}"
    )

print("\n[ sim_trades 近 14 条聚合（按日期 + 账户） ]")
for r in cur.execute(
    "SELECT trade_date AS d, account_id, COUNT(*) AS n FROM sim_trades "
    "GROUP BY d, account_id ORDER BY d DESC LIMIT 14"
):
    print(f"  {r['d']}  acct={r['account_id']}  trades={r['n']}")

print("\n[ sim_trades 最近 5 笔明细 ]")
for r in cur.execute(
    "SELECT trade_date, account_id, stock_code, direction, quantity, price, signal_reason "
    "FROM sim_trades ORDER BY id DESC LIMIT 5"
):
    print(
        f"  {r['trade_date']}  acct={r['account_id']}  {r['stock_code']}  "
        f"{r['direction']:<5}  {r['quantity']}@{r['price']:.3f}  {r['signal_reason'] or ''}"
    )

print("\n[ threshold_state 最近触发 ]")
rows = list(cur.execute(
    "SELECT stock_code, stock_name, rule_name, status, first_hit_date, fired_today "
    "FROM threshold_state WHERE status != 'inactive' "
    "ORDER BY first_hit_date DESC LIMIT 10"
))
if rows:
    for r in rows:
        print(
            f"  {r['stock_code']} {r['stock_name'] or '':<10}  {r['rule_name']:<22}  "
            f"status={r['status']:<10}  first_hit={r['first_hit_date']}  fired_today={r['fired_today']}"
        )
else:
    print("  (无 active 状态)")

print("\n[ 数据完整性检查 ]")
acct_ids = [r["id"] for r in cur.execute("SELECT id FROM sim_account")]
for aid in acct_ids:
    pos_n = cur.execute("SELECT COUNT(*) FROM sim_positions WHERE account_id=?", (aid,)).fetchone()[0]
    trade_n = cur.execute("SELECT COUNT(*) FROM sim_trades WHERE account_id=?", (aid,)).fetchone()[0]
    print(f"  acct={aid}  positions={pos_n}  trades={trade_n}")

con.close()
