#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成并推送每日复盘日报
"""
import sqlite3, os, sys
from datetime import date, datetime

project = r'C:\Users\Administrator\.openclaw\workspace\quant-learn'
db_path = os.path.join(project, 'data', 'sim_live_mirror.db')
pm_db = os.path.join(project, 'data', 'pm.db')
today = date.today().isoformat()

# ========== 1. 读取数据 ==========
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# learn 账户
cur.execute("SELECT * FROM sim_account WHERE account_name='learn'")
acct_row = cur.fetchone()
acct = dict(acct_row) if acct_row else {}

# 真实持仓 (排除 Test 脏数据)
cur.execute("""SELECT * FROM sim_positions 
    WHERE account_id=1 AND stock_name NOT LIKE 'Test%%' AND stock_code NOT LIKE '00000%%'""")
pos_rows = cur.fetchall()
positions = [dict(r) for r in pos_rows]

# 最新NAV (最近一条)
cur.execute("""SELECT * FROM sim_daily_nav 
    WHERE account_id=1 ORDER BY trade_date DESC LIMIT 1""")
nav_row = cur.fetchone()
nav = dict(nav_row) if nav_row else {}

# 昨日交易 (最近一个交易日)
cur.execute("""SELECT DISTINCT trade_date FROM sim_trades 
    WHERE account_id=1 ORDER BY trade_date DESC LIMIT 1""")
last_trade_date = cur.fetchone()
last_td = last_trade_date[0] if last_trade_date else today

cur.execute("""SELECT * FROM sim_trades 
    WHERE account_id=1 AND trade_date=? ORDER BY id""", (last_td,))
trade_rows = cur.fetchall()
last_trades = [dict(r) for r in trade_rows]

# config_sync 事件计数
cur.execute("""SELECT COUNT(*) as cnt FROM sim_account_events WHERE event_type='config_sync'""")
sync_cnt = cur.fetchone()[0]

# Test 脏数据计数
cur.execute("""SELECT COUNT(*) as cnt FROM sim_positions 
    WHERE stock_name LIKE 'Test%%' OR stock_code LIKE '00000%%'""")
test_cnt = cur.fetchone()[0]

conn.close()

# ========== 2. 分析计算 ==========
total_value = acct.get('total_value', 0)
cash = acct.get('cash', 0)
initial_cash = 200000  # 原始本金
cum_return = (total_value - initial_cash) / initial_cash * 100

# 持仓分析
alerts = []
pos_lines = []
for p in positions:
    name = p['stock_name']
    code = p['stock_code']
    cost = p['avg_cost']
    price = p['current_price']
    qty = p['quantity']
    pnl = p['pnl']
    pnl_pct = p['pnl_pct']
    stop = p['trailing_stop_price']
    highest = p['highest_price']
    
    cost_pnl = (price - cost) / cost * 100
    stop_dist = ((price - stop) / price * 100) if stop else None
    
    # 风险提示
    alert_items = []
    if stop and price <= stop * 1.02:
        alert_items.append('逼近止损')
    elif stop and price <= stop:
        alert_items.append('**已触发止损！**')
    if cost_pnl <= -5:
        alert_items.append('亏损>5%%')
    if cost_pnl >= 15:
        alert_items.append('盈利>15%%')
    
    alert_str = '，'.join(alert_items)
    if alert_str:
        alerts.append('%s(%s)：%s' % (name, code, alert_str))
    
    stop_str = '%.2f' % stop if stop else '未设置'
    mv = p['market_value']
    pos_lines.append('- **%s**(%s)：成本 ¥%.2f | 现价 ¥%.2f | 盈亏 **%+.2f%%** | 市值 ¥%.0f | 止损价 ¥%s' % (name, code, cost, price, cost_pnl, mv, stop_str))

# ========== 3. 生成日报 Markdown ==========
market_val = total_value - cash
nav_date = nav.get('trade_date', 'N/A')

report = '## 📊 模拟盘每日复盘 %s\n\n' % today
report += '**累计收益率 %+.2f%%** | 总资产 ¥%s | 现金 ¥%s | 持仓 ¥%s\n' % (cum_return, '{:,.0f}'.format(total_value), '{:,.0f}'.format(cash), '{:,.0f}'.format(market_val))
report += '\n---\n\n### 📌 持仓明细（%d 只）\n\n' % len(positions)
report += '\n'.join(pos_lines)
report += '\n\n---\n\n### 📝 最近操作（%s）\n\n' % last_td

if last_trades:
    for t in last_trades:
        direction = '买入' if t['direction'] == 'BUY' else '卖出'
        reason = t['signal_reason'] or '手动'
        report += '- %s **%s**(%s) %d股 @ ¥%.2f  \n  理由：%s\n' % (direction, t['stock_name'], t['stock_code'], t['quantity'], t['price'], reason)
else:
    report += '（无记录）\n'

report += '\n---\n\n### ⚙️ 系统状态\n\n'
report += '1. config_sync 事件 **%d 次**：initial_cash 配置不一致（config=100k vs DB=200k），建议统一配置\n' % sync_cnt
report += '2. sim_positions 中有 **%d 条测试脏数据**（Test0/Test1/Test2），需清理\n' % test_cnt
report += '3. 今日(%s) NAV 尚未写入 sim_daily_nav，请确认更新任务是否正常\n' % today
report += '4. real_portfolio(account_id=2) 在 sim_daily_nav 中无记录\n'

if alerts:
    report += '\n---\n\n### ⚠️ 风险提示\n\n'
    for a in alerts:
        report += '- %s\n' % a

report += '\n---\n\n*生成时间：%s*' % datetime.now().strftime('%Y-%m-%d %H:%M')

print(report)

# 保存报告
report_dir = os.path.join(project, 'data', 'reports')
os.makedirs(report_dir, exist_ok=True)
report_path = os.path.join(report_dir, '%s_daily_review.md' % today)
with open(report_path, 'w', encoding='utf-8') as f:
    f.write(report)
print('\n报告已保存：%s' % report_path)

# ========== 4. 推送企微 ==========
sys.path.insert(0, project)
from scripts.wecom_webhook import push_markdown

print('\n正在推送到企微群...')
result = push_markdown(report)
print('推送结果：%s' % result)
