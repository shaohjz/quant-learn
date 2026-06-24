#!/usr/bin/env python
"""理财师每日复盘脚本 - 由 cron 自动触发"""
import sqlite3
import os
from datetime import datetime, date
import json

ROOT = "C:/Users/Administrator/.openclaw/workspace/quant-learn"
SIM_DB = f"{ROOT}/data/sim_live_mirror.db"
PM_DB = f"{ROOT}/data/pm.db"
TODAY = date.today().strftime("%Y-%m-%d")

def get_connection(db_path):
    return sqlite3.connect(db_path)

def analyze_portfolio():
    """分析当前持仓和账户情况"""
    conn = get_connection(SIM_DB)
    cursor = conn.cursor()

    # 1. 账户概况
    cursor.execute("""
        SELECT account_name, cash, total_value, updated_at
        FROM sim_account
        WHERE id = 1
    """)
    account = cursor.fetchone()
    account_name, cash, total_value, acct_updated = account if account else (None, 0, 0, None)

    # 2. 当前持仓（quantity > 0）
    cursor.execute("""
        SELECT stock_code, stock_name, quantity, avg_cost, current_price,
               market_value, pnl, pnl_pct, updated_at,
               trailing_stop_price, highest_price
        FROM sim_positions
        WHERE account_id = 1 AND quantity > 0
        ORDER BY market_value DESC
    """)
    positions = cursor.fetchall()

    # 3. 今日 NAV（最新一日）
    cursor.execute("""
        SELECT trade_date, total_value, cash, market_value, daily_return, cumulative_return
        FROM sim_daily_nav
        WHERE account_id = 1
        ORDER BY trade_date DESC
        LIMIT 1
    """)
    nav = cursor.fetchone()

    # 4. 最近止损/止盈成交（最近7天）
    cursor.execute("""
        SELECT stock_code, stock_name, direction, trade_price, trade_volume,
               trade_time, strategy_name, '' as signal_reason
        FROM sim_fills
        WHERE account_id = 1
          AND trade_time >= datetime('now', '-7 days')
        ORDER BY trade_time DESC
        LIMIT 20
    """)
    recent_fills = cursor.fetchall()

    # 5. 今日策略信号（shadow signals 最近1天）
    cursor.execute("""
        SELECT stock_code, stock_name, signal_action, signal_rule, signal_reason, price, shadow_time
        FROM strategy_shadow_signals
        WHERE shadow_date >= ?
        ORDER BY shadow_time DESC
        LIMIT 20
    """, (TODAY,))
    recent_signals = cursor.fetchall()

    # 6. 阈值状态异常
    cursor.execute("""
        SELECT stock_code, stock_name, rule_name, status, notes, updated_at
        FROM threshold_state
        WHERE status NOT IN ('watching', 'executed')
        ORDER BY updated_at DESC
        LIMIT 10
    """)
    threshold_issues = cursor.fetchall()

    conn.close()

    return {
        "account": {
            "name": account_name,
            "cash": cash,
            "total_value": total_value,
            "updated_at": acct_updated
        },
        "nav": nav,
        "positions": positions,
        "recent_fills": recent_fills,
        "recent_signals": recent_signals,
        "threshold_issues": threshold_issues
    }

def check_stop_triggers(positions):
    """检查持仓的止损/止盈触发情况"""
    alerts = []
    for pos in positions:
        (code, name, qty, avg_cost, cur_price, mkt_val,
         pnl, pnl_pct, updated_at, trailing_stop, highest) = pos

        if qty == 0:
            continue

        # 止损检查：亏损超过10%
        if pnl_pct < -0.10:
            alerts.append({
                "type": "STOP_LOSS",
                "code": code,
                "name": name,
                "pnl_pct": pnl_pct,
                "msg": f"[警告] 止损预警：{name}({code}) 亏损 {pnl_pct*100:.1f}%，已超过-10%止损线"
            })

        # 止盈检查：盈利超过20%
        if pnl_pct > 0.20:
            alerts.append({
                "type": "TAKE_PROFIT",
                "code": code,
                "name": name,
                "pnl_pct": pnl_pct,
                "msg": f"[止盈] 止盈提示：{name}({code}) 盈利 {pnl_pct*100:.1f}%，可考虑分批止盈"
            })

        # trailing stop 检查
        if trailing_stop and cur_price:
            if cur_price < trailing_stop:
                alerts.append({
                    "type": "TRAILING_STOP",
                    "code": code,
                    "name": name,
                    "cur_price": cur_price,
                    "stop_price": trailing_stop,
                    "msg": f"[提醒] 移动止损触发：{name}({code}) 现价 {cur_price} 跌破移动止损价 {trailing_stop}"
                })

    return alerts

def generate_report(data):
    """生成日报 Markdown"""
    lines = []
    lines.append(f"# 理财师每日复盘 | {TODAY}")
    lines.append("")

    # 账户概况
    acct = data["account"]
    nav = data["nav"]
    lines.append("## 账户概况")
    if nav:
        trade_date, total_val, cash, mkt_val, daily_ret, cum_ret = nav
        lines.append(f"- 日期：{trade_date}")
        lines.append(f"- 总资产：**{total_val:.2f}** 元")
        lines.append(f"- 持仓市值：{mkt_val:.2f} 元")
        lines.append(f"- 可用现金：{cash:.2f} 元")
        lines.append(f"- 今日收益：{daily_ret*100:+.2f}%")
        lines.append(f"- 累计收益：{cum_ret*100:+.2f}%")
    else:
        lines.append(f"- 总资产：{acct['total_value']:.2f} 元")
        lines.append(f"- 可用现金：{acct['cash']:.2f} 元")
    lines.append("")

    # 持仓明细
    positions = data["positions"]
    lines.append("## 当前持仓")
    if positions:
        lines.append(f"共 **{len(positions)}** 只持仓：\n")
        for pos in positions:
            (code, name, qty, avg_cost, cur_price, mkt_val,
             pnl, pnl_pct, updated_at, trailing_stop, highest) = pos
            pnl_sign = "+" if pnl >= 0 else ""
            lines.append(f"### {name} ({code})")
            lines.append(f"- 持仓：{qty} 股，成本 {avg_cost:.3f}，现价 {cur_price:.3f}")
            lines.append(f"- 市值：{mkt_val:.2f} 元")
            lines.append(f"- 浮盈/亏：{pnl_sign}{pnl:.2f} 元（{pnl_sign}{pnl_pct*100:.2f}%）")
            if trailing_stop:
                lines.append(f"- 移动止损价：{trailing_stop:.3f}")
            if highest:
                lines.append(f"- 历史最高价：{highest:.3f}")
            lines.append("")
    else:
        lines.append("> 当前无持仓\n")
    lines.append("")

    # 止损/止盈预警
    alerts = check_stop_triggers(positions)
    lines.append("## 风险预警")
    if alerts:
        for alert in alerts:
            lines.append(f"- {alert['msg']}")
    else:
        lines.append("> 无止损/止盈触发预警")
    lines.append("")

    # 最近成交
    fills = data["recent_fills"]
    lines.append("## 近7日成交记录")
    if fills:
        for f in fills[:10]:
            code, name, direction, price, vol, trade_time, strategy, reason = f[:8]
            direction_text = "[买入]" if direction == "BUY" else "[卖出]"
            lines.append(f"- {direction_text} {trade_time[:16]} | {name}({code}) | {direction} {vol}股 @ {price:.3f} | 策略：{strategy or 'manual'}")
            if reason:
                lines.append(f"  > 原因：{reason}")
    else:
        lines.append("> 近7日无成交")
    lines.append("")

    # 策略信号
    signals = data["recent_signals"]
    lines.append("## 今日策略信号")
    if signals:
        for sig in signals[:10]:
            code, name, action, rule, reason, price, sig_time = sig
            action_text = "[买入]" if "BUY" in action else "[卖出]" if "SELL" in action else "[持仓]"
            lines.append(f"- {action_text} {sig_time} | {name}({code}) | {action} @ {price:.3f}")
            if reason:
                lines.append(f"  > {reason}")
    else:
        lines.append("> 今日无新策略信号")
    lines.append("")

    # 阈值异常
    threshold_issues = data["threshold_issues"]
    if threshold_issues:
        lines.append("## 阈值状态异常")
        for issue in threshold_issues:
            code, name, rule, status, notes, updated = issue
            lines.append(f"- {name}({code}) | 规则：{rule} | 状态：{status}")
            if notes:
                lines.append(f"  > {notes}")
        lines.append("")

    lines.append("---")
    lines.append(f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    lines.append("*数据来源：sim_live_mirror.db*")

    return "\n".join(lines)

def add_pm_task(title, description, priority="P2", task_type="bug"):
    """向 pm.db 添加 task"""
    conn = get_connection(PM_DB)
    cursor = conn.cursor()

    # 获取下一个 REQ ID
    cursor.execute("SELECT id FROM tasks ORDER BY id DESC LIMIT 1")
    last = cursor.fetchone()
    if last:
        last_num = int(last[0].split("-")[1])
        new_id = f"REQ-{last_num + 1:03d}"
    else:
        new_id = "REQ-001"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO tasks (id, type, title, description, status, priority,
                          created_at, updated_at, assigned_to, result_notes,
                          root_cause, fix_commit, work_notes)
        VALUES (?, ?, ?, ?, 'todo', ?, ?, ?, NULL, NULL, NULL, NULL, NULL)
    """, (new_id, task_type, title, description, priority, now, now))

    conn.commit()
    conn.close()
    print(f"[成功] 已添加 PM Task: {new_id} - {title}")
    return new_id

def detect_issues_and_log(data):
    """检测问题并自动提 PM task"""
    tasks_created = []

    # 问题1：threshold_state 中有 DATA_ANOMALY
    for issue in data.get("threshold_issues", []):
        code, name, rule, status, notes, updated = issue
        if notes and "ANOMALY" in notes:
            task_id = add_pm_task(
                title=f"数据异常：{name}({code}) - {notes[:50]}",
                description=f"threshold_state 中检测到数据异常：\n\n股票：{name}({code})\n规则：{rule}\n状态：{status}\n备注：{notes}\n\n更新时间：{updated}",
                priority="P1",
                task_type="bug"
            )
            tasks_created.append(task_id)

    # 问题2：有持仓但 nav 数据缺失（数据同步问题）
    if data["positions"] and not data["nav"]:
        task_id = add_pm_task(
            title="数据同步异常：存在持仓但 sim_daily_nav 无今日数据",
            description=f"检测日期：{TODAY}\n当前持仓数：{len(data['positions'])}\nsim_daily_nav 最新数据缺失，可能是每日NAV计算任务未运行。",
            priority="P1",
            task_type="bug"
        )
        tasks_created.append(task_id)

    return tasks_created

if __name__ == "__main__":
    print(f"开始复盘 {TODAY} ...")
    data = analyze_portfolio()

    print("\n检测到的问题：")
    tasks = detect_issues_and_log(data)
    if tasks:
        print(f"已创建 {len(tasks)} 个 PM Task")
    else:
        print("无新问题需要提报")

    print("\n生成日报...")
    report = generate_report(data)

    # 推送（通过 wecom_webhook 模块）
    import sys
    sys.path.insert(0, ROOT + "/scripts")
    from wecom_webhook import push_markdown

    print("\n推送到企微群...")
    ok = push_markdown(report)
    if ok:
        print("[成功] 日报推送成功")
    else:
        print("[警告] 推送失败，打印日报内容：")
        print(report)
