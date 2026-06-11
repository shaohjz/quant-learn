import sqlite3
conn = sqlite3.connect('data/sim_live_mirror.db')
conn.execute('UPDATE daily_snapshot SET total_asset=116500, total_market_value=85000, cash=31500 WHERE snapshot_date="2026-05-25"')
conn.commit()
print('✅ 已更新今日快照')
