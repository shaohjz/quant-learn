#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notify_intraday_watch.py — 盘中盯盘（定时运行，如 10:00/11:00/13:30/14:30）

检查持仓阈值触发（止盈/止损/回撤），有触发时推送企微，无触发时静默。

用法：
    cd C:/Users/Administrator/.openclaw/workspace/quant-learn
    python scripts/notify_intraday_watch.py
    python scripts/notify_intraday_watch.py --force   # 强制推送（无触发时也推）
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.db import get_conn
from sim.notifier import send_markdown, send_text
from sim.config import risk_params

# 阈值配置（与 config.yaml risk 保持一致）
_RISK = risk_params()
STOP_LOSS_PCT = _RISK["stop_loss_pct"]        # 止损 -0.08
TAKE_PROFIT_PCT = _RISK["take_profit_pct"]    # 止盈 +0.15
MAX_DRAWDOWN_PCT = 0.10   # 账户最大回撤告警阈值


def check_positions_for_alerts() -> list:
    """扫描持仓，返回触发告警的列表"""
    conn = get_conn()
    try:
        positions = conn.execute("""
            SELECT stock_code, stock_name, quantity, avg_cost,
                   current_price, market_value, pnl, pnl_pct,
                   max_price_since_buy
            FROM sim_positions
            WHERE account_id = 1 AND quantity > 0
            ORDER BY market_value DESC
        """).fetchall()
        alerts = []

        for pos in positions:
            code = pos["stock_code"]
            name = pos["stock_name"] or code
            cost = pos["avg_cost"]
            price = pos["current_price"] or 0
            qty = pos["quantity"]
            pnl_pct = pos["pnl_pct"] or 0
            max_price = pos["max_price_since_buy"] or cost

            # 止损触发
            if pnl_pct <= STOP_LOSS_PCT:
                alerts.append({
                    "type": "stop_loss",
                    "level": "🔴",
                    "code": code,
                    "name": name,
                    "pnl_pct": pnl_pct,
                    "msg": f"**{name}**({code}) 触发止损 {pnl_pct*100:.2f}%，成本¥{cost:.2f} 现价¥{price:.2f}",
                })

            # 止盈触发
            if pnl_pct >= TAKE_PROFIT_PCT:
                alerts.append({
                    "type": "take_profit",
                    "level": "🟢",
                    "code": code,
                    "name": name,
                    "pnl_pct": pnl_pct,
                    "msg": f"**{name}**({code}) 触发止盈 {pnl_pct*100:.2f}%，成本¥{cost:.2f} 现价¥{price:.2f}",
                })

            # 从最高点回撤超 5%
            if max_price > cost * 1.05:  # 只有盈利过才检查回撤
                drawdown = (price - max_price) / max_price
                if drawdown <= -0.05:
                    alerts.append({
                        "type": "drawdown",
                        "level": "🟡",
                        "code": code,
                        "name": name,
                        "drawdown": drawdown,
                        "msg": f"**{name}**({code}) 从最高¥{max_price:.2f} 回撤 {drawdown*100:.2f}%，当前¥{price:.2f}",
                    })

        return alerts
    finally:
        conn.close()


def check_account_drawdown() -> list:
    """检查账户级别回撤告警"""
    conn = get_conn()
    try:
        alerts = []
        # 取最近 20 个交易日的 NAV
        rows = conn.execute("""
            SELECT trade_date, total_value
            FROM sim_daily_nav
            WHERE account_id = 1
            ORDER BY trade_date DESC
            LIMIT 20
        """).fetchall()

        if len(rows) >= 2:
            current_nav = rows[0]["total_value"]
            max_nav = max(r["total_value"] for r in rows)
            drawdown = (current_nav - max_nav) / max_nav if max_nav else 0
            if drawdown <= -MAX_DRAWDOWN_PCT:
                alerts.append({
                    "type": "account_drawdown",
                    "level": "🔴",
                    "drawdown": drawdown,
                    "msg": f"**账户最大回撤** {drawdown*100:.2f}%，最高 ¥{max_nav:,.0f} → 当前 ¥{current_nav:,.0f}",
                })
        return alerts
    finally:
        conn.close()


def build_intraday_report(alerts: list, force: bool = False) -> str:
    """构建盘中盯盘报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []
    lines.append(f"## 📡 盘中盯盘 {now}")
    lines.append("")

    if not alerts:
        if force:
            lines.append("（当前无阈值触发，持仓正常 ✅）")
        else:
            # 无触发时返回 None，不推送
            return None
    else:
        lines.append(f"**⚠️ 触发告警 {len(alerts)} 条**")
        lines.append("")
        for a in alerts:
            lines.append(f"{a['level']} {a['msg']}")
        lines.append("")

    # 附上简要持仓快照
    conn = get_conn()
    try:
        acct = conn.execute(
            "SELECT cash, total_value FROM sim_account WHERE id = 1"
        ).fetchone()
        if acct:
            lines.append(
                f"*账户快照 总资产¥{acct['total_value']:,.0f} "
                f"现金¥{acct['cash']:,.0f}*"
            )
    finally:
        conn.close()

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="强制推送（无触发时也推）")
    args = parser.parse_args()

    alerts = check_positions_for_alerts()
    account_alerts = check_account_drawdown()
    all_alerts = alerts + account_alerts

    content = build_intraday_report(all_alerts, force=args.force)

    if content is None:
        print("✅ 无阈值触发，静默退出（用 --force 强制推送）")
        return 0

    print("推送内容：")
    print(content)
    print()

    # 有止损触发时用 text 类型（企微会 @all 更显眼）
    has_stop_loss = any(a["type"] == "stop_loss" for a in all_alerts)
    if has_stop_loss:
        # 止损触发用 text 格式，mention @all
        text_content = content.replace("## ", "").replace("**", "")
        ok = send_text(f"🚨 止损触发告警\n{content}")
    else:
        ok = send_markdown(content)

    if ok:
        print("✅ 盘中盯盘推送成功")
    else:
        print("❌ 推送失败，请检查 webhook 配置")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
