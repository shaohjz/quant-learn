import os, sys
os.environ['QUANT_DB_PATH'] = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db'
sys.path.insert(0, r'C:\Users\Administrator\.openclaw\workspace\quant-learn')
from sim.db import get_conn

conn = get_conn()
print('=== 持仓 ===')
for r in conn.execute('SELECT stock_code, stock_name, quantity, avg_cost, current_price, pnl_pct FROM sim_positions'):
    print(f'  {r[0]} {r[1]:>6} {r[2]:>4}股 cost={r[3]:.3f} cur={r[4]:.2f} pnl={r[5]:+.2f}%')

print()
print('=== 全部 live_mirror 交易 ===')
for r in conn.execute("SELECT trade_date, stock_code, stock_name, direction, quantity, price, signal_reason FROM sim_trades WHERE broker='live_mirror' ORDER BY id DESC LIMIT 10"):
    print(f'  {r[0]} {r[3]} {r[1]} {r[2]} {r[4]}股@{r[5]:.2f} | {r[6][:40]}')

print()
print('=== 账户 ===')
for r in conn.execute('SELECT account_name, cash, total_value, initial_cash FROM sim_account'):
    print(f'  {r[0]}: cash={r[1]:.2f}, total={r[2]:.2f}, initial={r[3]:.2f}')
conn.close()
