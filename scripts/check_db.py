import sqlite3
db = sqlite3.connect('data/sim_live_mirror.db')
c = db.cursor()

# 看看watchlist_history表
c.execute("SELECT * FROM watchlist_history LIMIT 20")
cols = [d[0] for d in c.description]
print('watchlist_history 列:', cols)
for r in c.fetchall():
    print(r)

print('\n---')

# 看看review_decisions表
c.execute("SELECT * FROM review_decisions LIMIT 10")
cols = [d[0] for d in c.description]
print('review_decisions 列:', cols)
for r in c.fetchall():
    print(r)

print('\n---')

# 看看strategy_shadow_signals表结构
c.execute("PRAGMA table_info(strategy_shadow_signals)")
cols = c.fetchall()
print('strategy_shadow_signals 结构:')
for col in cols:
    print(f'  {col}')

# 看看有哪些不同的股票出现在信号中
c.execute("SELECT DISTINCT stock_code, stock_name FROM strategy_shadow_signals ORDER BY stock_code")
stocks = c.fetchall()
print(f'\n信号中出现过的股票 ({len(stocks)}只):')
for s in stocks:
    print(f'  {s[0]} {s[1]}')

db.close()
