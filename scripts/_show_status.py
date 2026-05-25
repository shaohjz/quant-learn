import sqlite3
conn = sqlite3.connect('data/sim_live_mirror.db')
conn.row_factory = sqlite3.Row

print('=== 模拟持仓 ===')
for r in conn.execute('SELECT stock_code, stock_name, quantity, avg_cost FROM sim_positions WHERE quantity > 0'):
    print(f"  {r['stock_code']} {r['stock_name']:8s} {r['quantity']:4d}股 成本{r['avg_cost']:.3f}")

print()
print('=== 账户 ===')
acc = conn.execute('SELECT * FROM sim_account WHERE id=1').fetchone()
print(f"  现金: {acc['cash']:.0f}")

print()
print('=== 观察列表 (config.yaml 前5只) ===')
import yaml
cfg = yaml.safe_load(open('config.yaml', encoding='utf-8'))
wl = cfg.get('watchlist', {})
if isinstance(wl, dict):
    # 分层格式
    um = wl.get('user_manual', {})
    for i, (code, v) in enumerate(list(um.items())[:8]):
        name = v.get('name', '')
        enabled = v.get('enabled', True)
        print(f"  {code} {name:8s} {'✓' if enabled else '✗'}")
else:
    for i, item in enumerate(list(wl)[:8]):
        print(f"  {item}")
conn.close()
