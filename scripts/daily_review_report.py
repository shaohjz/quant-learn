#!/usr/bin/env python3
"""
daily_review_report.py - 理财师每日复盘汇报

1. 复盘今日交易：读取模拟盘持仓，分析表现，检查止损/止盈
2. 提需求单：发现问题后在 pm.db 添加 task
3. 生成日报：输出日报 Markdown 并保存

用法: python scripts/daily_review_report.py
"""

import sqlite3
import json
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

SIM_DB = DATA / "sim.db"
PM_DB = DATA / "pm.db"
REPORT_DIR = DATA
TODAY = date.today().isoformat()
REPORT_FILE = REPORT_DIR / f"daily_report_{TODAY.replace('-', '')}.md"

# 止损/止盈阈值
STOP_LOSS_PCT = -0.10   # -10%
TAKE_PROFIT_PCT = 0.20  # +20%


def get_connection(db_path):
    if not db_path.exists():
        print(f"[ERR] DB not found: {db_path}")
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def run_sync():
    """运行 sync_live.py 同步真实持仓"""
    sync_script = ROOT / "scripts" / "sync_live.py"
    if not sync_script.exists():
        print(f"[WARN] {sync_script} not found, skipping sync")
        return False
    print(f"[Sync] Running {sync_script.name} ...")
    result = subprocess.run(
        [sys.executable, str(sync_script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("[Sync] Done")
        return True
    else:
        print(f"[Sync] Failed (rc={result.returncode}): {result.stderr[:200]}")
        return False


def fetch_account_info():
    """读取账户信息"""
    conn = get_connection(SIM_DB)
    if not conn:
        return {}
    cur = conn.cursor()
    cur.execute("SELECT * FROM sim_account WHERE account_name='default'")
    row = cur.fetchone()
    account = dict(row) if row else {}
    conn.close()
    return account


def fetch_positions():
    """从 sim.db 读取当前持仓"""
    conn = get_connection(SIM_DB)
    if not conn:
        return []
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM sim_positions
        WHERE account_id = (SELECT id FROM sim_account WHERE account_name='default')
    """)
    rows = cur.fetchall()
    positions = [dict(r) for r in rows]
    conn.close()
    return positions


def add_task_to_pm(title, description, priority="P2", task_type="bug"):
    """在 pm.db 中添加 task，返回新task id"""
    conn = get_connection(PM_DB)
    if not conn:
        print("[ERR] Cannot open pm.db")
        return None
    cur = conn.cursor()

    # 生成新ID：找最大数字
    cur.execute("SELECT id FROM tasks ORDER BY id DESC LIMIT 1")
    last = cur.fetchone()
    if last:
        try:
            num = int(last["id"].split("-")[1]) + 1
        except Exception:
            num = 4
    else:
        num = 4
    new_id = f"REQ-{num:03d}"

    now = datetime.now().isoformat(timespec="seconds")
    cur.execute(
        """INSERT INTO tasks (id, type, title, description, status, priority, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'todo', ?, ?, ?)""",
        (new_id, task_type, title, description, priority, now, now),
    )
    conn.commit()
    conn.close()
    print(f"[PM]  新增需求单 {new_id} [{priority}]: {title}")
    return new_id


def check_sim_live_mirror_structure():
    """检查 sim_live_mirror.db 结构 — 目前仅含 review_reflections，这是正常的"""
    return None  # 跳过检查，sim_live_mirror.db 本来就不需要持仓表


def analyze_positions(positions):
    """
    分析持仓，返回 (alerts, issues)
    alerts: 止损/止盈触发列表
    issues: 数据质量问题列表
    """
    alerts = []
    issues = []

    for p in positions:
        code = p.get("stock_code", "")
        name = p.get("stock_name", "")
        pnl_pct = p.get("pnl_pct", 0)
        price = p.get("current_price", 0)
        cost = p.get("avg_cost", 0)
        qty = p.get("quantity", 0)

        # 止损/止盈检查
        if pnl_pct <= STOP_LOSS_PCT:
            alerts.append({
                "level": "stop_loss",
                "msg": f"🛑 止损触发 {code}({name}) 亏损 {pnl_pct:.1%}，成本={cost:.2f}，现价={price:.2f}",
                "code": code,
                "pnl_pct": pnl_pct,
            })
        elif pnl_pct >= TAKE_PROFIT_PCT:
            alerts.append({
                "level": "take_profit",
                "msg": f"🎯 止盈触发 {code}({name}) 盈利 {pnl_pct:.1%}，成本={cost:.2f}，现价={price:.2f}",
                "code": code,
                "pnl_pct": pnl_pct,
            })

        # 数据质量检查
        if not price or price <= 0:
            issues.append({
                "type": "数据缺失",
                "desc": f"{code}({name}) 当前价格异常: {price}",
                "priority": "P1",
            })
        if not cost or cost <= 0:
            issues.append({
                "type": "数据缺失",
                "desc": f"{code}({name}) 成本价异常: {cost}",
                "priority": "P1",
            })
        if not qty:
            issues.append({
                "type": "数据异常",
                "desc": f"{code}({name}) 持仓数量为0",
                "priority": "P2",
            })

    return alerts, issues


def generate_report(positions, account, alerts, issues, new_task_ids):
    """生成日报 Markdown 文本"""
    lines = []
    sep = "="*50
    lines.append(f"# 📊 模拟盘日报 {TODAY}")
    lines.append("")

    if not positions:
        lines.append("> ⚠️ **当前无持仓数据**")
        lines.append("> 可能原因：")
        lines.append("> 1. 未执行 `python scripts/sync_live.py` 同步真实持仓")
        lines.append("> 2. `real_holdings.json` 为空或不存在")
        lines.append("> 3. 模拟盘尚未开始交易")
        lines.append("")
        lines.append("**建议**：先完善 `data/real_holdings.json` 并执行同步脚本。")
        lines.append("")
        lines.append(f"---\n*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        return "\n".join(lines)

    # ---- 账户概览 ----
    cash = account.get("cash", 0)
    total_value = account.get("total_value", 0)
    initial_cash = account.get("initial_cash", 10000)
    total_pnl = total_value - initial_cash
    total_pnl_pct = (total_pnl / initial_cash * 100) if initial_cash else 0
    market_value = sum(p.get("market_value", 0) for p in positions)

    lines.append("## 💰 账户概览")
    lines.append(f"- 总市值：**¥{total_value:,.2f}**")
    lines.append(f"- 持仓市值：¥{market_value:,.2f}（{market_value/total_value:.1%}）")
    lines.append(f"- 可用现金：¥{cash:,.2f}（{cash/total_value:.1%}）")
    pnl_str = f"¥{total_pnl:+,.2f}"  # + prefix handled by :+
    lines.append(f"- 累计收益：**{pnl_str}（{total_pnl_pct:+.1f}%）**")
    lines.append("")

    # ---- 风险预警 ----
    if alerts:
        lines.append("## 🚨 风险预警")
        lines.append("")
        for a in alerts:
            lines.append(f"- {a['msg']}")
        lines.append("")

    # ---- 持仓明细 ----
    lines.append("## 📋 持仓明细")
    lines.append("")
    # 表头
    lines.append(f"| 代码 | 名称 | 数量 | 成本 | 现价 | 市值 | 盈亏 | 盈亏% |")
    lines.append("|------|------|------|------|------|------|------|-------|")

    sorted_positions = sorted(positions, key=lambda x: x.get("pnl_pct", 0))
    for p in sorted_positions:
        code = p.get("stock_code", "")
        name = p.get("stock_name", "")[:6]
        qty = p.get("quantity", 0)
        cost = p.get("avg_cost", 0)
        price = p.get("current_price", 0)
        mkt_val = p.get("market_value", 0)
        pnl = p.get("pnl", 0)
        pnl_pct = p.get("pnl_pct", 0)

        pnl_str = f"{pnl:+,.0f}" if pnl else "0"
        pnl_pct_str = f"{pnl_pct:+.1%}" if pnl_pct else "0%"

        lines.append(
            f"| {code} | {name} | {qty} | {cost:.2f} | {price:.2f} "
            f"| {mkt_val:,.0f} | {pnl_str} | {pnl_pct_str} |"
        )
    lines.append("")

    # ---- 今日关注 ----
    lines.append("## 🔍 今日关注")
    lines.append("")
    if positions:
        sorted_by_pnl = sorted(positions, key=lambda x: x.get("pnl_pct", 0))
        worst = sorted_by_pnl[0]
        best = sorted_by_pnl[-1]
        lines.append(
            f"- 📉 最差：**{worst.get('stock_name')}**（{worst.get('stock_code')}）"
            f"  {worst.get('pnl_pct', 0):+.1%}"
        )
        lines.append(
            f"- 📈 最佳：**{best.get('stock_name')}**（{best.get('stock_code')}）"
            f"  {best.get('pnl_pct', 0):+.1%}"
        )
    lines.append("- 大盘情绪：待接入（可对接情绪分析脚本）")
    lines.append("- 板块热点：待接入")
    lines.append("")

    # ---- 数据质量问题 ----
    if issues:
        lines.append("## ⚠️ 数据质量问题")
        lines.append("")
        for iss in issues:
            lines.append(f"- [{iss['priority']}] {iss['type']}: {iss['desc']}")
        lines.append("")

    # ---- 新增需求单 ----
    if new_task_ids:
        lines.append("## 📝 今日新增需求单")
        lines.append("")
        for t in new_task_ids:
            lines.append(f"- `{t['id']}` [{t['priority']}] {t['title']}")
        lines.append("")

    lines.append("---")
    lines.append(f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    lines.append("")

    return "\n".join(lines)


def main():
    print(f"{'='*60}")
    print(f"  📈 理财师每日复盘 {TODAY}")
    print(f"{'='*60}")

    # Step 0: 同步真实持仓
    print("\n[Step 0/5] 同步真实持仓...")
    real_json = DATA / "real_holdings.json"
    if real_json.exists():
        print(f"  找到 {real_json.name}，执行同步...")
        ok = run_sync()
        if not ok:
            print("  [WARN] 同步失败，尝试直接读取持仓...")
    else:
        print(f"  [WARN] {real_json} 不存在，跳过同步")
        print("  [INFO] 如果 sim.db 中已有持仓数据，将继续...")

    # Step 1: 读取账户和持仓
    print("\n[Step 1/5] 读取模拟盘数据...")
    account = fetch_account_info()
    positions = fetch_positions()

    if not positions:
        print("  ⚠️ 无持仓数据！")
        report = generate_report([], {}, [], [], [])
        REPORT_FILE.write_text(report, encoding="utf-8")
        print(f"\n日报（空）已保存：{REPORT_FILE}")
        # 仍输出报告内容
        print("\n" + "="*60)
        print(report)
        print("="*60)
        return report

    print(f"  持仓数：{len(positions)}")
    print(f"  账户总值：¥{account.get('total_value', 0):,.2f}")

    # Step 2: 分析持仓
    print("\n[Step 2/5] 分析持仓表现...")
    alerts, issues = analyze_positions(positions)
    print(f"  止损/止盈预警：{len(alerts)} 条")
    print(f"  数据质量问题：{len(issues)} 条")
    for a in alerts:
        print(f"    {a['msg']}")

    # Step 3: 提需求单
    print("\n[Step 3/4] 提需求单...")
    new_task_ids = []
    for iss in issues:
        task_id = add_task_to_pm(
            title=f"[{iss['type']}] {iss['desc'][:60]}",
            description=(
                f"来源：每日复盘 {TODAY}\n\n"
                f"问题类型：{iss['type']}\n"
                f"详细描述：{iss['desc']}\n"
            ),
            priority=iss["priority"],
            task_type="bug" if "bug" in iss.get("type", "").lower() or iss["type"] in ["数据缺失", "数据异常"] else "story",
        )
        if task_id:
            new_task_ids.append({"id": task_id, "title": iss["desc"], "priority": iss["priority"]})

    if not issues:
        print("  无新问题，未新增需求单")

    # Step 4: 生成日报
    print("\n[Step 4/4] 生成日报...")
    report = generate_report(positions, account, alerts, issues, new_task_ids)

    # 保存日报
    REPORT_FILE.write_text(report, encoding="utf-8")
    print(f"  日报已保存：{REPORT_FILE}")

    # 也写到 latest_daily_report.md（供读取）
    latest = DATA / "latest_daily_report.md"
    latest.write_text(report, encoding="utf-8")

    # 打印日报
    print("\n" + "="*60)
    print(report)
    print("="*60)

    return report


if __name__ == "__main__":
    main()
