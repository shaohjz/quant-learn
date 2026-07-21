"""研发经理日报查询脚本"""
import sqlite3
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# PM DB
pm_db = os.path.join(ROOT, "data", "pm.db")
conn = sqlite3.connect(pm_db)
conn.row_factory = sqlite3.Row

print("=== PM Task Status Summary ===")
rows = conn.execute("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status ORDER BY cnt DESC").fetchall()
for r in rows:
    print(f"  {r['status']:15s} : {r['cnt']}")

print("\n=== PM Task Type Summary ===")
rows2 = conn.execute("SELECT type, COUNT(*) as cnt FROM tasks GROUP BY type").fetchall()
for r in rows2:
    print(f"  {r['type']:15s} : {r['cnt']}")

print("\n=== Recent PM Tasks (last 20) ===")
rows3 = conn.execute("SELECT id, type, title, status, priority, updated_at FROM tasks ORDER BY updated_at DESC LIMIT 20").fetchall()
for r in rows3:
    title = (r['title'] or '')[:70]
    print(f"  {r['id']:20s} | {r['type']:6s} | {r['status']:12s} | {r['priority']:3s} | {title} | {r['updated_at']}")

print("\n=== Tasks in_progress (active development) ===")
rows4 = conn.execute("SELECT id, type, title, status, priority, assigned_to, work_notes, updated_at FROM tasks WHERE status='in_progress' ORDER BY priority").fetchall()
for r in rows4:
    title = (r['title'] or '')[:60]
    wn = (r['work_notes'] or '')[-80:]
    print(f"  {r['id']} | {r['priority']} | {r['assigned_to'] or 'unassigned':20s} | {title}")
    if wn:
        print(f"    work_notes: ...{wn}")

print("\n=== Open Bugs ===")
rows5 = conn.execute("SELECT id, title, status, priority, updated_at FROM tasks WHERE type='bug' AND status NOT IN ('fixed','verified','closed') ORDER BY updated_at DESC").fetchall()
for r in rows5:
    print(f"  {r['id']} | {r['priority']} | {r['status']} | {(r['title'] or '')[:70]} | {r['updated_at']}")

conn.close()

# Sim DB
sim_db = os.path.join(ROOT, "data", "sim_live_mirror.db")
conn2 = sqlite3.connect(sim_db)
conn2.row_factory = sqlite3.Row

print("\n=== Sim Positions ===")
pos = conn2.execute("SELECT account_id, COUNT(*) as cnt, SUM(market_value) as mv FROM sim_positions WHERE quantity>0 GROUP BY account_id").fetchall()
for p in pos:
    print(f"  account_id={p['account_id']}: {p['cnt']} positions, MV={round(p['mv'] or 0, 2)}")

print("\n=== Recent Trades (2026-07-15+) ===")
trades = conn2.execute("SELECT trade_date, direction, COUNT(*) as cnt, SUM(amount) as amt FROM sim_trades WHERE trade_date >= '2026-07-15' GROUP BY trade_date, direction ORDER BY trade_date DESC").fetchall()
for t in trades:
    print(f"  {t['trade_date']} {t['direction']:5s}: {t['cnt']} trades, amt={round(t['amt'] or 0, 2)}")

print("\n=== Sim Accounts ===")
acc = conn2.execute("SELECT * FROM sim_account").fetchall()
for a in acc:
    keys = a.keys()
    cash = a['cash'] if 'cash' in keys else 'N/A'
    initial = a['initial_cash'] if 'initial_cash' in keys else 'N/A'
    total = a['total_value'] if 'total_value' in keys else 'N/A'
    name = a['account_name'] if 'account_name' in keys else ''
    print(f"  id={a['id']} name={name} cash={cash} initial={initial} total={total}")

# NAV
print("\n=== Recent NAV (last 10) ===")
nav = conn2.execute("SELECT trade_date, account_id, total_value, cumulative_return FROM sim_daily_nav ORDER BY trade_date DESC LIMIT 10").fetchall()
for n in nav:
    print(f"  {n['trade_date']} | acct={n['account_id']} | value={round(n['total_value'],2)} | ret={round(n['cumulative_return']*100 if n['cumulative_return'] else 0,2)}%")

conn2.close()

# Check for today's daily reports
reports_dir = os.path.join(ROOT, "daily_reports")
print(f"\n=== Daily Reports Dir: {reports_dir} ===")
if os.path.isdir(reports_dir):
    for f in sorted(os.listdir(reports_dir), reverse=True)[:5]:
        print(f"  {f}")

print("\nDone.")
