import sqlite3, json, os
from datetime import date, datetime, timedelta

today = date.today().isoformat()
yesterday = (date.today() - timedelta(days=1)).isoformat()
print(f'=== 今日日期: {today} ===')
print(f'=== 昨日日期: {yesterday} ===')

# 1. 模拟成交 - 今日
db_path = 'data/sim_live_mirror.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # sim_trades today
    cur.execute("SELECT * FROM sim_trades WHERE trade_date=? ORDER BY trade_time, id", (today,))
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(f'\nsim_trades 今日({today}): {len(rows)} 笔')
    for r in rows:
        d = dict(zip(cols, r))
        print(f"  [{d['trade_time']}] {d['direction']} {d['stock_code']}({d['stock_name']}) @ {d['price']} x {d['quantity']} | 信号:{d['signal_reason']} | 上下文:{d['trade_context']}")
    
    # sim_trades yesterday (for cross-check)
    cur.execute("SELECT * FROM sim_trades WHERE trade_date=? ORDER BY trade_time, id", (yesterday,))
    cols2 = [d[0] for d in cur.description]
    rows2 = cur.fetchall()
    print(f'\nsim_trades 昨日({yesterday}): {len(rows2)} 笔')
    for r in rows2:
        d = dict(zip(cols2, r))
        print(f"  [{d['trade_time']}] {d['direction']} {d['stock_code']}({d['stock_name']}) @ {d['price']} x {d['quantity']} | 信号:{d['signal_reason']}")
    
    # sim_positions now
    cur.execute("SELECT * FROM sim_positions")
    cols_p = [d[0] for d in cur.description]
    rows_p = cur.fetchall()
    print(f'\nsim_positions 当前持仓: {len(rows_p)} 个')
    for r in rows_p:
        d = dict(zip(cols_p, r))
        print(f"  {d['stock_code']}({d['stock_name']}) 持仓:{d['quantity']} 成本:{d['cost_price']} 现价:{d.get('current_price', 'N/A')}")
    
    # sim_account
    cur.execute("SELECT * FROM sim_account")
    cols_a = [d[0] for d in cur.description]
    rows_a = cur.fetchall()
    print(f'\nsim_account:')
    for r in rows_a:
        d = dict(zip(cols_a, r))
        print(f"  {d}")
    
    # strategy_shadow_signals (recent)
    cur.execute("SELECT * FROM strategy_shadow_signals ORDER BY created_at DESC LIMIT 20")
    cols_s = [d[0] for d in cur.description]
    rows_s = cur.fetchall()
    print(f'\nstrategy_shadow_signals 最近20条:')
    for r in rows_s:
        d = dict(zip(cols_s, r))
        print(f"  {d}")
    
    # review_reflections
    cur.execute("SELECT * FROM review_reflections ORDER BY id DESC LIMIT 10")
    cols_r = [d[0] for d in cur.description]
    rows_r = cur.fetchall()
    print(f'\nreview_reflections 最近10条:')
    for r in rows_r:
        d = dict(zip(cols_r, r))
        print(f"  {d}")
    
    conn.close()
else:
    print('sim_live_mirror.db not found')

# 2. 实盘持仓
real_path = 'data/real_holdings.json'
if os.path.exists(real_path):
    with open(real_path) as f:
        real = json.load(f)
    print(f'\nreal_holdings: {json.dumps(real, ensure_ascii=False, indent=2)[:5000]}')
else:
    print('\nreal_holdings.json not found')

# 3. 今日复盘文件
review_path = f'docs/reviews/{today}.md'
if os.path.exists(review_path):
    with open(review_path, encoding='utf-8') as f:
        content = f.read()
    print(f'\n=== 今日复盘 {today}.md ===')
    print(content[:8000])
else:
    print(f'\nreview file not found: {review_path}')
    # list available review files
    review_dir = 'docs/reviews'
    if os.path.exists(review_dir):
        files = sorted(os.listdir(review_dir))
        print(f'available review files: {files[-10:]}')

# 4. PM tasks
pm_path = 'data/pm.db'
if os.path.exists(pm_path):
    conn = sqlite3.connect(pm_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f'\npm db tables: {tables}')
    if 'tasks' in tables:
        cur.execute('SELECT * FROM tasks ORDER BY created_at DESC LIMIT 20')
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print(f'pm tasks: {len(rows)} rows')
        for r in rows:
            print(dict(zip(cols, r)))
    conn.close()
else:
    print('\npm.db not found')
