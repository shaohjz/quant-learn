"""Backfill daily_return for REQ-061 fix"""
import sys
sys.path.insert(0, '.')
from datetime import date
from scripts.daily_review import write_daily_nav, fetch_account, fetch_positions, load_config
from sim.config import get_account_config

cfg = load_config()
account = fetch_account(1)
config_initial = get_account_config(1)['initial_cash']

# Re-run write_daily_nav for 2026-06-19 with fixed code
positions = fetch_positions(1)
nav = write_daily_nav(
    account_id=1,
    target_date=date(2026, 6, 19),
    account=account,
    positions=positions,
    initial_cash=config_initial,
    pause_daily_return=False,
    basis_warnings=None,
)
print('2026-06-19 nav result:', nav)

# Check if there's trade data for 2026-06-17 and 2026-06-18
import sqlite3
conn = sqlite3.connect('data/sim_live_mirror.db')
cur = conn.cursor()
for d in ['2026-06-17', '2026-06-18']:
    cur.execute('SELECT COUNT(*) FROM sim_trades WHERE trade_date = ?', (d,))
    cnt = cur.fetchone()[0]
    print(f'sim_trades on {d}: {cnt} rows')
conn.close()
print('Done')
