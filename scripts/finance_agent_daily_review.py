#!/usr/bin/env python3
"""理财师每日复盘脚本 - 由 cron 触发"""

import sqlite3
import datetime
import json
import os
import sys

WORKSPACE = r"C:\Users\Administrator\.openclaw\workspace\quant-learn"
PM_DB = os.path.join(WORKSPACE, "data", "pm.db")
SIM_DB = os.path.join(WORKSPACE, "data", "sim_live_mirror.db")
REVIEW_DIR = os.path.join(WORKSPACE, "docs", "reviews")

def get_connection(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def analyze_positions(conn):
    """分析持仓，检查止损止盈"""
    cur = conn.cursor()
    cur.execute("SELECT * FROM sim_positions ORDER BY account_id, stock_code")
    positions = [dict(r) for r in cur.fetchall()]
    
    alerts = []
    stop_loss_triggered = []
    
    for p in positions:
        cost = p.get("avg_cost") or 0
        cur_price = p.get("current_price") or 0
        tstop = p.get("trailing_stop_price")
        pnl_pct = p.get("pnl_pct") or 0
        stock = p.get("stock_code")
        name = p.get("stock_name")
        
        if cost == 0:
            continue
        
        # 检查止损：当前价 <= 成本 * 0.92（8%止损线）
        stop_line = cost * 0.92
        if cur_price <= stop_line:
            stop_loss_triggered.append({
                "stock": f"{stock} {name}",
                "cost": cost,
                "cur": cur_price,
                "stop_line": round(stop_line, 2),
                "pnl_pct": round(pnl_pct, 2)
            })
        
        # 检查 trailing stop
        if tstop and tstop > 0 and cur_price <= tstop:
            stop_loss_triggered.append({
                "stock": f"{stock} {name} (追踪止损)",
                "cost": cost,
                "cur": cur_price,
                "stop_line": tstop,
                "pnl_pct": round(pnl_pct, 2)
            })
        
        # 严重浮亏预警（-10%以上）
        if pnl_pct <= -10 and pnl_pct > -100:
            alerts.append(f"⚠️ {stock} {name} 浮亏 {pnl_pct:.2f}%，接近止损线")
    
    return positions, alerts, stop_loss_triggered

def check_data_freshness(conn):
    """检查数据更新时间"""
    cur = conn.cursor()
    cur.execute("SELECT MAX(updated_at) FROM sim_positions")
    row = cur.fetchone()
    latest_pos = row[0] if row else None
    
    cur.execute("SELECT MAX(updated_at) FROM sim_account")
    row = cur.fetchone()
    latest_acct = row[0] if row else None
    
    return latest_pos, latest_acct

def generate_daily_report(positions, alerts, stop_loss_triggered, latest_pos, latest_acct):
    """生成日报文本"""
    today = datetime.date.today().strftime("%Y-%m-%d")
    
    # 按账户分组
    acct_data = {}
    for p in positions:
        aid = p.get("account_id")
        if aid not in acct_data:
            acct_data[aid] = {"positions": [], "total_mv": 0, "total_pnl": 0}
        acct_data[aid]["positions"].append(p)
        acct_data[aid]["total_mv"] += p.get("market_value") or 0
        acct_data[aid]["total_pnl"] += p.get("pnl") or 0
    
    lines = []
    lines.append(f"📊 **量化模拟盘每日复盘 {today}**")
    lines.append("")
    
    # 数据新鲜度
    lines.append(f"🕐 数据更新时间: positions={latest_pos or '未知'}, account={latest_acct or '未知'}")
    
    # 止损触发警报
    if stop_loss_triggered:
        lines.append("")
        lines.append("🚨 **止损触发警报** 🚨")
        for s in stop_loss_triggered:
            lines.append(f"  ❌ {s['stock']}: 现价 {s['cur']} 跌破止损线 {s['stop_line']}，浮亏 {s['pnl_pct']}%")
    else:
        lines.append("✅ 今日无止损触发")
    
    # 持仓概览
    lines.append("")
    lines.append("**持仓概览**")
    for aid, data in acct_data.items():
        lines.append(f"  账户 {aid}: {len(data['positions'])} 只持仓，市值 ¥{data['total_mv']:.2f}，浮动 ¥{data['total_pnl']:+.2f}")
    
    # 关注事项
    if alerts:
        lines.append("")
        lines.append("**⚠️ 需要关注**")
        for a in alerts:
            lines.append(f"  {a}")
    
    # 数据新鲜度警告
    if latest_pos:
        try:
            import datetime as dt
            pos_dt = dt.datetime.strptime(latest_pos[:19], "%Y-%m-%d %H:%M:%S")
            delta = dt.datetime.now() - pos_dt
            if delta.days > 1:
                lines.append("")
                lines.append(f"⚠️ **数据已过期 {delta.days} 天！** 最后更新: {latest_pos}")
        except:
            pass
    
    lines.append("")
    lines.append("---")
    lines.append("理财师 Agent 自动生成")
    
    return "\n".join(lines)

def add_pm_task(conn, task_id, title, description, status, priority):
    """向 PM DB 添加任务"""
    cur = conn.cursor()
    cur.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
    if cur.fetchone():
        return False  # 已存在
    
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        INSERT INTO tasks (id, type, title, description, status, priority, created_at, updated_at)
        VALUES (?, 'bug', ?, ?, ?, ?, ?, ?)
    """, (task_id, title, description, status, priority, now, now))
    conn.commit()
    return True

def main():
    today = datetime.date.today().strftime("%Y-%m-%d")
    print(f"[{today} 20:08] 理财师开始每日复盘...")
    
    # 连接数据库
    if not os.path.exists(SIM_DB):
        print(f"❌ sim_live_mirror.db 不存在: {SIM_DB}")
        # 尝试从备份恢复
        bak = SIM_DB + ".req057_20260602_161641.bak"
        if os.path.exists(bak):
            import shutil
            shutil.copy(bak, SIM_DB)
            print(f"✅ 从备份恢复: {bak}")
        else:
            print("❌ 无备份可恢复")
            return
    
    sim_conn = get_connection(SIM_DB)
    pm_conn = get_connection(PM_DB)
    
    # 分析持仓
    positions, alerts, stop_loss_triggered = analyze_positions(sim_conn)
    
    # 检查数据新鲜度
    latest_pos, latest_acct = check_data_freshness(sim_conn)
    
    # 生成日报
    report = generate_daily_report(positions, alerts, stop_loss_triggered, latest_pos, latest_acct)
    
    # 保存日报
    os.makedirs(REVIEW_DIR, exist_ok=True)
    review_path = os.path.join(REVIEW_DIR, f"{today}.md")
    with open(review_path, "w", encoding="utf-8") as f:
        f.write(f"# 理财师复盘 {today}\n\n{report}\n")
    print(f"✅ 日报已保存: {review_path}")
    
    # 检查是否需要提需求单
    issues = []
    
    # 问题1: 数据过期
    if latest_pos:
        try:
            import datetime as dt
            pos_dt = dt.datetime.strptime(latest_pos[:19], "%Y-%m-%d %H:%M:%S")
            delta = dt.datetime.now() - pos_dt
            if delta.days > 1:
                issues.append({
                    "id": "BUG-019",
                    "title": "BUG-019: sim_live_mirror.db 数据过期/写入链路中断",
                    "desc": f"持仓数据最后更新时间：{latest_pos}，距今已 {delta.days} 天。sim_live_mirror 写入链路可能中断，需要检查 vnpy OmsEngine 运行状态和数据同步 cron。",
                    "priority": "P0"
                })
        except:
            pass
    
    # 问题2: 止损未设置
    no_stop = [p for p in positions if (p.get("trailing_stop_price") is None or p.get("trailing_stop_price") == 0) and (p.get("avg_cost") or 0) > 0]
    if no_stop:
        stock_list = ", ".join([p["stock_code"] + " " + p["stock_name"] for p in no_stop[:3]])
        issues.append({
            "id": "REQ-059",
            "title": "REQ-059: 持仓追踪止损价格未全覆盖 - 部分仓位无止损保护",
            "desc": f"发现 {len(no_stop)} 只持仓 trailing_stop_price 为 NULL 或 0，包括：{stock_list}。需要确认初始化建仓时是否自动设置止损价。",
            "priority": "P1"
        })
    
    # 写入 PM DB
    for issue in issues:
        is_new = add_pm_task(pm_conn, issue["id"], issue["title"], issue["desc"], "in_progress", issue["priority"])
        status = "新增" if is_new else "已存在"
        print(f"  PM任务 {status}: {issue['id']}")
    
    sim_conn.close()
    pm_conn.close()
    
    print("")
    print("=== 日报内容 ===")
    print(report)
    print("=== 结束 ===")

if __name__ == "__main__":
    main()
