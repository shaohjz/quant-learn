#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notify_opening_brief.py — 开盘快报（9:31）

读取开盘成交情况，推送开盘快报到企微群。

用法：
    cd C:/Users/Administrator/.openclaw/workspace/quant-learn
    python scripts/notify_opening_brief.py
"""

import sys
from pathlib import Path
from datetime import datetime, date as Date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.db import get_conn
from sim.notifier import send_markdown


def build_opening_brief() -> str:
    """构建开盘快报 Markdown 内容"""
    today = Date.today().isoformat()
    now = datetime.now().strftime("%H:%M")
    conn = get_conn()
    try:
        # 今日开盘阶段成交记录（9:30-9:35 之间的 trades）
        trades = conn.execute("""
            SELECT direction, stock_code, stock_name, price, quantity,
                   amount, signal_reason, executed_at
            FROM sim_trades
            WHERE account_id = 1 AND trade_date = ?
            ORDER BY executed_at ASC
        """, (today,)).fetchall()

        lines = []
        lines.append(f"## 🔔 开盘快报 {today} {now}")
        lines.append("")

        if not trades:
            lines.append("（开盘阶段暂无成交记录）")
            lines.append("")
            lines.append("*可能原因：集合竞价未触发成交，或今日无信号*")
            return "\n".join(lines)

        buy_trades = [t for t in trades if t["direction"] == "BUY"]
        sell_trades = [t for t in trades if t["direction"] == "SELL"]

        if buy_trades:
            lines.append(f"**🟢 买入成交 {len(buy_trades)} 笔**")
            for t in buy_trades:
                name = t["stock_name"] or t["stock_code"]
                code = t["stock_code"]
                qty = t["quantity"]
                price = t["price"]
                amt = t["amount"] or qty * price
                reason = t["signal_reason"] or "—"
                lines.append(
                    f"- {name}({code}) {qty}股 @ ¥{price:.2f} ≈ ¥{amt:,.0f}"
                )
                lines.append(f"  > 信号：{reason}")
            lines.append("")

        if sell_trades:
            lines.append(f"**🔴 卖出成交 {len(sell_trades)} 笔**")
            for t in sell_trades:
                name = t["stock_name"] or t["stock_code"]
                code = t["stock_code"]
                qty = t["quantity"]
                price = t["price"]
                amt = t["amount"] or qty * price
                reason = t["signal_reason"] or "—"
                lines.append(
                    f"- {name}({code}) {qty}股 @ ¥{price:.2f} ≈ ¥{amt:,.0f}"
                )
                lines.append(f"  > 信号：{reason}")
            lines.append("")

        # 账户快照
        acct = conn.execute(
            "SELECT cash, total_value FROM sim_account WHERE id = 1"
        ).fetchone()
        if acct:
            lines.append(f"**账户快照** 总资产 ¥{acct['total_value']:,.2f} | 现金 ¥{acct['cash']:,.2f}")

        return "\n".join(lines)
    finally:
        conn.close()


def main():
    content = build_opening_brief()
    print("推送内容：")
    print(content)
    print()
    ok = send_markdown(content)
    if ok:
        print("✅ 开盘快报推送成功")
    else:
        print("❌ 推送失败，请检查 webhook 配置")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
