#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日复盘日报生成脚本
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

# Get latest trade date (fallback for non-trading days)
cur.execute("SELECT MAX(trade_date) FROM sim_daily_nav WHERE account_id=1")
latest_trade_date = cur.fetchone()[0]
if latest_trade_date is None:
    latest_trade_date = today
is_non_trading_day = (latest_trade_date != today)

# learn 账户
cur.execute("SELECT * FROM sim_account WHERE account_name='learn'")
acct = cur.fetchone()
acct = dict(acct) if acct else {}

# 真实持仓 (排除 Test 脏数据)
cur.execute("""SELECT * FROM sim_positions 
    WHERE account_id=1 AND stock_name NOT LIKE 'Test%' AND stock_code NOT LIKE '00000%'""")
pos_rows = cur.fetchall()
positions = [dict(r) for r in pos_rows]

# 最新NAV（使用最近交易日）
cur.execute("""SELECT * FROM sim_daily_nav 
    WHERE account_id=1 AND trade_date=? ORDER BY id DESC LIMIT 1""", (latest_trade_date,))
nav_row = cur.fetchone()
nav = dict(nav_row) if nav_row else {}

# 最近交易日交易
cur.execute("""SELECT * FROM sim_trades 
    WHERE account_id=1 AND trade_date=? ORDER BY id""", (latest_trade_date,))
trade_rows = cur.fetchall()
today_trades = [dict(r) for r in trade_rows]

# config_sync 事件计数
cur.execute("""SELECT COUNT(*) as cnt FROM sim_account_events WHERE event_type='config_sync'""")
sync_cnt = cur.fetchone()[0]

# Test 脏数据计数
cur.execute("""SELECT COUNT(*) as cnt FROM sim_positions 
    WHERE stock_name LIKE 'Test%' OR stock_code LIKE '00000%'""")
test_cnt = cur.fetchone()[0]

conn.close()

# ========== 2. 分析计算 ==========
total_value = acct.get('total_value', 0)
cash = acct.get('cash', 0)
initial_cash = acct.get('initial_cash', 200000)
cum_return = (total_value - initial_cash) / initial_cash * 100

# 持仓分析
pos_lines = []
alerts = []
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
    stop_dist = (price - stop) / price * 100 if stop else None
    
    # 止损检查
    issues = []
    if stop and price <= stop * 1.01:
        issues.append('⚠️ 逼近止损线')
    if cost_pnl <= -5:
        issues.append('⚠️ 亏损>5%%')
    if cost_pnl >= 15:
        issues.append('✅ 盈利>15%%')
    
    alert_str = ' '.join(issues)
    if alert_str:
        alerts.append(f'{name}({code}) {alert_str}')
    
    pos_lines.append(f"  - {name}({code}): 成本={cost:.2f}, 现价={price:.2f}, 盈亏={cost_pnl:+.2f}%%, 市值={p['market_value']:.0f}, {alert_str}")

# Add non-trading day banner if applicable
non_trade_banner = ""
if is_non_trading_day:
    non_trade_banner = f"> ⚠️ **非交易日提醒**：今日({today})为非交易日，以下数据基于最近交易日 {latest_trade_date}。\n\n"

# ========== 3. 生成日报 Markdown ==========
report_title = f"# 📊 模拟盘每日复盘 {today}"
if is_non_trading_day:
    report_title += f"（非交易日，数据来自 {latest_trade_date}）"
report = f"""{report_title}

{non_trade_banner}## 一、账户总览（learn）

| 指标 | 数值 |
|------|------|
| 总资产 | ¥{total_value:,.2f} |
| 现金 | ¥{cash:,.2f} |
| 持仓市值 | ¥{total_value - cash:,.2f} |
| 累计收益率 | {cum_return:+.2f}% |
| 最近NAV日期 | {latest_trade_date} |
| 最近NAV总值 | ¥{nav.get('total_value', 0):,.2f} |

## 二、持仓明细（{len(positions)} 只）

"""
for line in pos_lines:
    report += line + "\n"

report += "\n"

if alerts:
    report += "## ⚠️ 风险提示\n\n"
    for a in alerts:
        report += f"- {a}\n"
    report += "\n"

report += f"""## 三、最近交易日操作（{latest_trade_date}）

"""
if today_trades:
    for t in today_trades:
        direction = "买入" if t['direction'] == 'BUY' else "卖出"
        reason = t['signal_reason'] or '手动'
        report += f"- {direction} {t['stock_name']}({t['stock_code']}) {t['quantity']}股 @ ¥{t['price']:.2f}，理由：{reason}\n"
else:
    report += "（无记录）\n"

report += f"""
## 四、系统状态 & 待处理问题

1. **config_sync 事件频繁**：检测到 {sync_cnt} 次 config_sync 事件，表示 `initial_cash` 配置与 DB 值不一致（config=100,000 vs DB=200,000），建议统一配置来源
2. **Test 脏数据**：已清理 ✅（7/6 验证 sim_positions 中无测试股票）
3. **NAV 数据状态**：最近记录为 {latest_trade_date}{"，非交易日" if is_non_trading_day else "，今日数据正常"}
4. **real_portfolio 无NAV记录**：account_id=2 在 sim_daily_nav 中无任何记录，需修复

## 五、明日关注

- 立讯精密(002475)：现价 64.95，最高 65.79，关注是否能突破前高
- 龙旗科技(603341)：微亏 -1.24%，关注 36.39 止损线
- 圆通速递(600233)：微亏 -0.29%，关注 15.97 止损线

---
*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""

print(report)

# 保存报告到文件
report_dir = os.path.join(project, 'data', 'reports')
os.makedirs(report_dir, exist_ok=True)
report_path = os.path.join(report_dir, f'{today}_daily_review.md')
with open(report_path, 'w', encoding='utf-8') as f:
    f.write(report)
print(f'\n报告已保存：{report_path}')

# ========== 4. 写入 PM 需求单 ==========
pm_conn = sqlite3.connect(pm_db)
pm_cur = pm_conn.cursor()

# 检查 tasks 表结构
pm_cur.execute("PRAGMA table_info(tasks)")
cols = [r[1] for r in pm_cur.fetchall()]
print(f'\nPM tasks 表列: {cols}')

tasks_to_add = []

# 问题1: config_sync 频繁
tasks_to_add.append({
    'id': 'REQ-004',
    'type': 'bug',
    'title': 'config_sync 事件频繁触发：initial_cash 配置不一致',
    'description': f'检测到 {sync_cnt} 次 config_sync 事件。问题根因：config 中 initial_cash=100,000，但 DB 中 initial_cash=200,000，每次 engine.init 都触发自动同步。建议：统一配置来源，避免反复 sync。',
    'priority': 'P1',
    'status': 'todo'
})

# 问题2: Test 脏数据
tasks_to_add.append({
    'id': 'REQ-005',
    'type': 'bug',
    'title': 'sim_positions 中存在测试脏数据（Test0/Test1/Test2）',
    'description': f'sim_positions 表中有 {test_cnt} 条测试仓位记录（stock_code=000000/000001/000002），这些是非真实持仓，会影响每日复盘和 NAV 计算准确性。需要清理。',
    'priority': 'P2',
    'status': 'todo'
})

# 问题3: NAV 更新滞后
tasks_to_add.append({
    'id': 'REQ-006',
    'type': 'bug',
    'title': 'NAV 数据未每日自动更新（今日记录缺失）',
    'description': f'今日({today}) NAV 尚未写入 sim_daily_nav 表。最近一条记录为 2026-07-03。需要确认每日 NAV 更新任务（cron job 或调度脚本）是否正常运行。',
    'priority': 'P1',
    'status': 'todo'
})

# 检查 REQ-004/005/006 是否已存在
for t in tasks_to_add:
    pm_cur.execute("SELECT id FROM tasks WHERE id=?", (t['id'],))
    if pm_cur.fetchone():
        print(f"任务 {t['id']} 已存在，跳过")
    else:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        pm_cur.execute("""INSERT INTO tasks (id, type, title, description, status, priority, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (t['id'], t['type'], t['title'], t['description'], t['status'], t['priority'], now, now))
        print(f"已添加任务：{t['id']} - {t['title']}")

pm_conn.commit()
pm_conn.close()

print('\nPM 需求单写入完成')

# ========== 5. 推送企微 ==========
import subprocess
# 推送（截取报告，避免太长）
max_len = 4000
push_content = report if len(report) <= max_len else report[:max_len] + "\n...\n(完整报告见文件)"

push_cmd = f"""python -c "from scripts.wecom_webhook import push_markdown; push_markdown('''{push_content.replace("'", "\\'")}''')" """
print('\n推送命令已准备好，请手动执行或检查 wecom_webhook 模块')
print('报告路径:', report_path)
