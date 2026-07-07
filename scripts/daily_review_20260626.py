#!/usr/bin/env python3
"""
daily_review_20260626.py - 理财师每日复盘汇报 (2026-06-26)
"""
import sqlite3
import os
from datetime import datetime

ROOT = r'C:\Users\Administrator\.openclaw\workspace\quant-learn'
SIM_DB = os.path.join(ROOT, 'data', 'sim_live_mirror.db')
PM_DB = os.path.join(ROOT, 'data', 'pm.db')
TODAY = '2026-06-26'

# 1. 读取持仓数据
conn = sqlite3.connect(SIM_DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 账户信息
cur.execute("SELECT * FROM sim_account ORDER BY id")
accounts = [dict(r) for r in cur.fetchall()]

# 持仓
cur.execute("SELECT * FROM sim_positions ORDER BY account_id, stock_code")
positions = [dict(r) for r in cur.fetchall()]

# armed 卖出信号
cur.execute("SELECT * FROM threshold_state WHERE status IN ('armed', 'confirmed') ORDER BY stock_code")
armed = [dict(r) for r in cur.fetchall()]

# 最近交易（6月2日后应为空）
cur.execute("SELECT * FROM sim_trades WHERE trade_date >= '2026-06-03' ORDER BY trade_date DESC")
recent_trades = [dict(r) for r in cur.fetchall()]

# 最新NAV
cur.execute("SELECT * FROM sim_daily_nav ORDER BY trade_date DESC LIMIT 3")
latest_nav = [dict(r) for r in cur.fetchall()]

conn.close()

# 2. 分析
# 数据过期天数
data_last_update = '2026-06-02'
days_stale = 24  # 6月2日到6月26日

# 计算持仓市值（基于过期价格）
total_market_value = sum(p['market_value'] for p in positions)
total_cash = sum(a['cash'] for a in accounts)
total_asset = total_market_value + total_cash

# 分类持仓
acct1_positions = [p for p in positions if p['account_id'] == 1]
acct2_positions = [p for p in positions if p['account_id'] == 2]

# 止损检查（基于过期价格）
stop_loss_triggered = []
for p in positions:
    if p['pnl_pct'] and p['pnl_pct'] < -10:
        stop_loss_triggered.append(p)

# 止盈检查
take_profit_triggered = []
for p in positions:
    if p['pnl_pct'] and p['pnl_pct'] > 20:
        take_profit_triggered.append(p)

# 3. 生成日报 Markdown
report_lines = []
report_lines.append(f"# 📊 量化模拟盘每日复盘 | {TODAY}")
report_lines.append("")
report_lines.append("> ⚠️ **数据严重过期警告**")
report_lines.append(f"> 模拟盘数据最后更新于 **2026-06-02**，距今已 **{days_stale} 天**，以下分析基于过期价格，仅供参考。")
report_lines.append("> 今日无新交易数据写入，数据同步链路疑似中断。")
report_lines.append("")

report_lines.append("## 💰 账户总览")
report_lines.append("")
for acct in accounts:
    report_lines.append(f"### 账户 {acct['id']} ({acct['account_name']})")
    report_lines.append(f"- 初始资金: ¥{acct['initial_cash']:,.2f}")
    report_lines.append(f"- 可用现金: ¥{acct['cash']:,.2f}")
    report_lines.append(f"- 持仓市值: ¥{sum(p['market_value'] for p in positions if p['account_id']==acct['id']):,.2f}")
    report_lines.append(f"- 总资产(过期): ¥{acct['total_value']:,.2f}")
    report_lines.append(f"- 最后更新: {acct['updated_at']}")
    report_lines.append("")

report_lines.append("## 📈 持仓明细（价格过期，请勿作为交易依据）")
report_lines.append("")
report_lines.append("| 账户 | 代码 | 名称 | 数量 | 成本 | 现价(06-02) | 市值 | 盈亏 | 盈亏% | 追踪止损 |")
report_lines.append("|------|------|------|------|------|------------|------|------|--------|----------|")
for p in positions:
    emoji = "📈" if (p['pnl_pct'] or 0) > 0 else "📉"
    report_lines.append(
        f"| {p['account_id']} | {p['stock_code']} | {p['stock_name']} | {p['quantity']} | "
        f"{p['avg_cost']:.2f} | {p['current_price']:.2f} | ¥{p['market_value']:.0f} | "
        f"{p['pnl']:.0f} | {emoji}{p['pnl_pct']:.1f}% | {p['trailing_stop_price'] or '未设置'} |"
    )
report_lines.append("")

report_lines.append("## 🚨 风险控制检查")
report_lines.append("")
if stop_loss_triggered:
    report_lines.append(f"### ❌ 止损触发 ({len(stop_loss_triggered)} 只)")
    for p in stop_loss_triggered:
        report_lines.append(f"- {p['stock_code']} {p['stock_name']}: 亏损 {p['pnl_pct']:.1f}%，需确认当前价格")
else:
    report_lines.append("### ✅ 止损检查: 无触发（基于过期数据）")
    report_lines.append("")

if take_profit_triggered:
    report_lines.append(f"### 🎯 止盈触发 ({len(take_profit_triggered)} 只)")
    for p in take_profit_triggered:
        report_lines.append(f"- {p['stock_code']} {p['stock_name']}: 盈利 {p['pnl_pct']:.1f}%，需确认当前价格")
else:
    report_lines.append("### ✅ 止盈检查: 无触发（基于过期数据）")
    report_lines.append("")

# armed 未执行
if armed:
    report_lines.append(f"### ⚠️ 已触发未卖出信号 ({len(armed)} 条，自 06-02 起积压)")
    for a in armed:
        report_lines.append(f"- {a['stock_code']} {a['stock_name']}: {a['rule_name']} | 状态={a['status']} | 触发价={a['first_hit_price']} | 确认价={a['close_price']} | 更新={a['updated_at']}")
else:
    report_lines.append("### ✅ 无积压卖出信号")
report_lines.append("")

report_lines.append("## 🔍 今日交易")
report_lines.append("")
if recent_trades:
    for t in recent_trades:
        report_lines.append(f"- {t['trade_date']} {t.get('trade_time', '')} | {t['direction']} {t['stock_code']} {t['stock_name']} @ {t['price']:.2f} x {t['quantity']} | 理由: {t['signal_reason']}")
else:
    report_lines.append("**今日无新交易**（数据同步中断，实际交易情况未知）")
report_lines.append("")

report_lines.append("## 🛠️ 系统状态 & 待处理需求")
report_lines.append("")
report_lines.append("### 严重问题")
report_lines.append("1. **数据同步中断**: sim_live_mirror 数据停留在 2026-06-02，距今 24 天，写入链路中断")
report_lines.append("2. **armed 信号积压**: 6 条卖出信号自 6 月 2 日起积压未执行")
report_lines.append("3. **account_id=1 initial_cash 异常**: 初始资金 200000 但现金仅 13872，需与 REQ-057 一并处理")
report_lines.append("")
report_lines.append("### PM 待处理需求（P1 未解决）")
report_lines.append("- REQ-065: account_id=1 累计收益率异常 (-78.12%) — 状态: open")
report_lines.append("- REQ-060: 西部材料建仓信号与 MA20 严重偏离 — 状态: in_progress")
report_lines.append("- REQ-063: 豫能控股 take_profit armed 但 6 月 10 日才止损离场 — 状态: open")
report_lines.append("- REQ-059: 持仓追踪止损价格未全覆盖 — 状态: in_progress")
report_lines.append("- REQ-058: SELL 成交 signal_reason 为空 — 状态: in_progress")
report_lines.append("")

report_lines.append("## 📌 明日行动")
report_lines.append("")
report_lines.append("1. **紧急**: 修复 sim_live_mirror 数据同步链路，确认 vnpy OmsEngine 运行状态")
report_lines.append("2. **紧急**: 处理积压的 6 条 armed 卖出信号（确认当前价格后决定是否执行）")
report_lines.append("3. **高优**: 推进 REQ-065/REQ-060/REQ-063 的调查与修复")
report_lines.append("4. **建议**: 添加数据新鲜度监控，数据超过 1 天未更新自动告警")
report_lines.append("")

report_lines.append("---")
report_lines.append(f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 数据截止: 2026-06-02 (过期 {days_stale} 天)*")
report_lines.append("*⚠️ 本报告基于过期数据，仅供系统诊断参考，不构成投资建议*")

report = "\n".join(report_lines)

# 4. 保存日报
report_path = os.path.join(ROOT, 'data', f'daily_report_{TODAY.replace("-", "")}.md')
with open(report_path, 'w', encoding='utf-8') as f:
    f.write(report)
print(f"Report saved to: {report_path}")
print()
print(report)

# 5. 推送到企微群
import subprocess
result = subprocess.run(
    [sys.executable, '-c', 
     f"from scripts.wecom_webhook import push_markdown; push_markdown('''{report}''')"],
    cwd=ROOT,
    capture_output=True,
    text=True,
)
print("\nPush result:", result.returncode)
if result.stdout:
    print("stdout:", result.stdout)
if result.stderr:
    print("stderr:", result.stderr)
