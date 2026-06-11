#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notify_closing_review.py — 收盘复盘（15:05）

汇总当日交易、持仓盈亏、净值变化，推送收盘复盘到企微群。

用法：
    cd C:/Users/Administrator/.openclaw/workspace/quant-learn
    python scripts/notify_closing_review.py
"""

import sys
from pathlib import Path
from datetime import datetime, date as Date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.db import get_conn
from sim.notifier import send_markdown
from sim.reporter import generate_daily_report


def build_closing_review() -> str:
    """构建收盘复盘 Markdown 内容"""
    today = Date.today().isoformat()
    now = datetime.now().strftime("%H:%M")
    conn = get_conn()
    try:
        lines = []
        lines.append(f"## 🔔 收盘复盘 {today} {now}")
        lines.append("")

        # 账户信息
        acct = conn.execute(
            "SELECT cash, total_value, initial_cash FROM sim_account WHERE id = 1"
        ).fetchone()

        if not acct:
            return f"⚠️ **收盘复盘** {today}\n\n账户不存在，请检查数据库。"

        initial_cash = acct["initial_cash"] or 20000
        cash = acct["cash"]
        total_value = acct["total_value"]
        pnl = total_value - initial_cash
        pnl_pct = (pnl / initial_cash * 100) if initial_cash else 0

        lines.append(f"**账户** 总资产 ¥{total_value:,.2f} | 现金 ¥{cash:,.2f}")
        emoji = "🟢" if pnl >= 0 else "🔴"
        lines.append(f"{emoji} 累计盈亏 ¥{pnl:+,.2f}（{pnl_pct:+.2f}%）")
        lines.append("")

        # 今日交易
        trades = conn.execute("""
            SELECT direction, stock_code, stock_name, price, quantity,
                   amount, signal_reason
            FROM sim_trades
            WHERE account_id = 1 AND trade_date = ?
            ORDER BY id
        """, (today,)).fetchall()

        if trades:
            buy_t = [t for t in trades if t["direction"] == "BUY"]
            sell_t = [t for t in trades if t["direction"] == "SELL"]
            lines.append(f"**今日交易 {len(trades)} 笔** （买 {len(buy_t)} / 卖 {len(sell_t)}）")
            for t in trades:
                name = t["stock_name"] or t["stock_code"]
                code = t["stock_code"]
                side = "买" if t["direction"] == "BUY" else "卖"
                emoji_t = "🟢" if t["direction"] == "BUY" else "🔴"
                amt = t["amount"] or (t["price"] * t["quantity"])
                lines.append(
                    f"{emoji_t} {side} {name}({code}) "
                    f"{t['quantity']}股 @ ¥{t['price']:.2f} ≈ ¥{amt:,.0f}"
                )
                if t["signal_reason"]:
                    lines.append(f"  > {t['signal_reason']}")
            lines.append("")
        else:
            lines.append("（今日无交易）")
            lines.append("")

        # 持仓盈亏
        positions = conn.execute("""
            SELECT stock_code, stock_name, quantity, avg_cost,
                   current_price, market_value, pnl, pnl_pct
            FROM sim_positions
            WHERE account_id = 1 AND quantity > 0
            ORDER BY market_value DESC
        """).fetchall()

        if positions:
            lines.append(f"**持仓 {len(positions)} 只**")
            total_pos_pnl = 0.0
            for pos in positions:
                code = pos["stock_code"]
                name = pos["stock_name"] or code
                qty = pos["quantity"]
                cost = pos["avg_cost"]
                price = pos["current_price"] or 0
                pnl_val = pos["pnl"] or ((price - cost) * qty)
                pnl_pct_val = pos["pnl_pct"] or ((price - cost) / cost if cost else 0) * 100
                emoji_p = "🟢" if pnl_val >= 0 else "🔴"
                lines.append(
                    f"{emoji_p} **{name}**({code}) {qty}股 "
                    f"成本¥{cost:.2f} 收¥{price:.2f} "
                    f"{pnl_val:+,.0f}({pnl_pct_val:+.2f}%)"
                )
                total_pos_pnl += pnl_val
            lines.append("")
            emoji_ttl = "🟢" if total_pos_pnl >= 0 else "🔴"
            lines.append(f"{emoji_ttl} **持仓总盈亏：¥{total_pos_pnl:+,.2f}**")
        else:
            lines.append("（当前无持仓）")

        lines.append("")
        lines.append("*数据来源：sim.db | 收盘后快照*")
        return "\n".join(lines)
    finally:
        conn.close()


def main():
    content = build_closing_review()
    print("推送内容：")
    print(content)
    print()
    ok = send_markdown(content)
    if ok:
        print("✅ 收盘复盘推送成功")
    else:
        print("❌ 推送失败，请检查 webhook 配置")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
