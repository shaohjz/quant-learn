#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notify_auction_brief.py — 集合竞价快报（9:24）

读取当前持仓 + 实时价格，推送集合竞价快照到企微群。

用法：
    cd C:/Users/Administrator/.openclaw/workspace/quant-learn
    python scripts/notify_auction_brief.py
"""

import sys
from pathlib import Path

# 把项目根加入 sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from datetime import datetime
from sim.db import get_conn
from sim.notifier import send_markdown
from sim.realtime_price import get_latest_prices
from sim.config import get as cfg_get


def build_auction_brief() -> str:
    """构建集合竞价快报 Markdown 内容"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = get_conn()
    try:
        # 读取账户信息
        acct = conn.execute(
            "SELECT id, account_name, cash, total_value, initial_cash "
            "FROM sim_account WHERE id = 1"
        ).fetchone()

        if not acct:
            return f"⚠️ **集合竞价快报** {now}\n\n账户不存在，请检查数据库。"

        cash = acct["cash"]
        total_value = acct["total_value"]
        initial_cash = acct["initial_cash"] or cfg_get("account.initial_cash", 20000)
        pnl = total_value - initial_cash
        pnl_pct = (pnl / initial_cash * 100) if initial_cash else 0

        # 读取持仓
        positions = conn.execute(
            "SELECT stock_code, stock_name, quantity, avg_cost, current_price, "
            "market_value, pnl, pnl_pct "
            "FROM sim_positions WHERE account_id = 1 AND quantity > 0 "
            "ORDER BY market_value DESC"
        ).fetchall()

        lines = []
        lines.append(f"## 📊 集合竞价快报 {now}")
        lines.append("")
        lines.append(f"**账户总览**")
        lines.append(f"- 总资产：¥{total_value:,.2f}")
        lines.append(f"- 可用现金：¥{cash:,.2f}")
        lines.append(f"- 累计盈亏：¥{pnl:,.2f}（{pnl_pct:+.2f}%）")
        lines.append("")

        if not positions:
            lines.append("（当前无持仓）")
        else:
            lines.append(f"**持仓 {len(positions)} 只**")
            for pos in positions:
                code = pos["stock_code"]
                name = pos["stock_name"] or code
                qty = pos["quantity"]
                cost = pos["avg_cost"]
                price = pos["current_price"] or 0
                pnl_val = pos["pnl"] or 0
                pnl_pct_val = (pos["pnl_pct"] or 0) * 100
                emoji = "🟢" if pnl_val >= 0 else "🔴"
                lines.append(
                    f"{emoji} **{name}**({code}) {qty}股 "
                    f"成本¥{cost:.2f} 现价¥{price:.2f} "
                    f"{pnl_val:+,.2f}({pnl_pct_val:+.2f}%)"
                )
            lines.append("")

        lines.append("*数据来源：sim.db 实时快照*")
        return "\n".join(lines)
    finally:
        conn.close()


def main():
    content = build_auction_brief()
    print("推送内容：")
    print(content)
    print()
    ok = send_markdown(content)
    if ok:
        print("✅ 集合竞价快报推送成功")
    else:
        print("❌ 推送失败，请检查 webhook 配置")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
