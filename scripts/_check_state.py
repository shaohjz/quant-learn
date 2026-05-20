import sqlite3, os
db = os.path.join(os.path.dirname(__file__), '..', 'data', 'sim_live_mirror.db')
c = sqlite3.connect(db); c.row_factory = sqlite3.Row
print('--- positions ---')
for r in c.execute('SELECT stock_code, stock_name, quantity, avg_cost, current_price, pnl_pct FROM sim_positions ORDER BY stock_code'):
    print(f"  {r['stock_code']} {r['stock_name']}: {r['quantity']}@{r['avg_cost']:.3f} cur={r['current_price']:.2f} pnl%={r['pnl_pct']:.2f}")
print('--- account ---')
for r in c.execute('SELECT cash, total_value FROM sim_account'):
    print(f"  cash={r['cash']:.2f}  total_value={r['total_value']:.2f}")
print('--- 002342 trades ---')
for r in c.execute("SELECT trade_date, direction, price, quantity, signal_reason FROM sim_trades WHERE stock_code='002342' ORDER BY id"):
    print(f"  {r['trade_date']} {r['direction']} {r['quantity']}@{r['price']} | {r['signal_reason']}")
