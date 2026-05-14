"""
sim/reporter.py
报告生成器 — 生成每日模拟盘报告 + 净值曲线图
"""

import os
from datetime import date as Date
from sim.db import get_conn

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _fmt_money(v):
    if v is None:
        return "—"
    return f"{float(v):,.2f}"


def _fmt_pct(v):
    if v is None:
        return "—"
    return f"{float(v)*100:+.2f}%"


def generate_daily_report(trade_date: Date = None,
                          signals: list = None,
                          account_id: int = 1) -> str:
    """
    生成每日模拟盘报告（纯文本/Markdown）
    """
    trade_date = trade_date or Date.today()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 账户状态
            cur.execute(
                "SELECT account_name, initial_cash, cash, total_value "
                "FROM sim_account WHERE id = %s", (account_id,))
            acct = cur.fetchone()

            # 今日交易
            cur.execute(
                "SELECT direction, stock_code, stock_name, price, quantity, "
                "amount, commission, tax, signal_reason "
                "FROM sim_trades WHERE account_id = %s AND trade_date = %s "
                "ORDER BY id", (account_id, trade_date))
            trades = cur.fetchall()

            # 当前持仓
            cur.execute(
                "SELECT stock_code, stock_name, quantity, avg_cost, "
                "current_price, market_value, pnl, pnl_pct "
                "FROM sim_positions WHERE account_id = %s AND quantity > 0",
                (account_id,))
            positions = cur.fetchall()

            # 今日净值
            cur.execute(
                "SELECT total_value, cash, market_value, daily_return, "
                "cumulative_return, max_drawdown "
                "FROM sim_daily_nav WHERE account_id = %s AND trade_date = %s",
                (account_id, trade_date))
            nav = cur.fetchone()
    finally:
        conn.close()

    lines = []
    lines.append(f"📊 模拟盘日报 | {trade_date}")
    lines.append("=" * 36)

    # 账户概况
    if acct:
        initial = float(acct[1])
        cash = float(acct[2])
        total = float(acct[3])
        pnl = total - initial
        lines.append("")
        lines.append("💰 账户概况")
        lines.append(f"  总资产: ¥{_fmt_money(total)}")
        lines.append(f"  可用资金: ¥{_fmt_money(cash)}")
        lines.append(f"  总盈亏: ¥{_fmt_money(pnl)} ({_fmt_pct(pnl/initial if initial else 0)})")

    # 净值数据
    if nav:
        lines.append("")
        lines.append("📈 净值数据")
        lines.append(f"  日收益率: {_fmt_pct(nav[3])}")
        lines.append(f"  累计收益: {_fmt_pct(nav[4])}")
        lines.append(f"  最大回撤: {_fmt_pct(-abs(float(nav[5])) if nav[5] else 0)}")

    # 今日信号
    if signals:
        lines.append("")
        lines.append("🎯 今日信号")
        for s in signals:
            emoji = "🟢" if s["signal"] == "BUY" else "🔴" if s["signal"] == "SELL" else "⚪"
            lines.append(f"  {emoji} {s['name']}({s['code']}): {s['signal']}")
            lines.append(f"     价格: ¥{s['price']:.2f}")
            lines.append(f"     原因: {', '.join(s['reasons'])}")
            # 关键指标
            ind = s.get("indicators", {})
            if ind:
                lines.append(f"     RSI={ind.get('RSI','')}, K={ind.get('K','')}, "
                             f"D={ind.get('D','')}, J={ind.get('J','')}")
                lines.append(f"     MACD={ind.get('MACD','')}, MA5={ind.get('MA5','')}, "
                             f"MA10={ind.get('MA10','')}")

    # 今日交易
    if trades:
        lines.append("")
        lines.append("📋 今日交易")
        for t in trades:
            direction = t[0]
            emoji = "🟢买入" if direction == "BUY" else "🔴卖出"
            lines.append(f"  {emoji} {t[2]}({t[1]})")
            lines.append(f"     {t[4]}股 × ¥{float(t[3]):.4f} = ¥{_fmt_money(t[5])}")
            fee_parts = [f"佣金¥{float(t[6]):.2f}"]
            if t[7] and float(t[7]) > 0:
                fee_parts.append(f"印花税¥{float(t[7]):.2f}")
            lines.append(f"     费用: {' + '.join(fee_parts)}")
            if t[8]:
                lines.append(f"     信号: {t[8]}")
    else:
        lines.append("")
        lines.append("📋 今日无交易")

    # 当前持仓
    lines.append("")
    if positions:
        lines.append("📦 当前持仓")
        for p in positions:
            pnl_pct = float(p[7]) if p[7] else 0
            emoji = "📈" if pnl_pct > 0 else "📉" if pnl_pct < 0 else "➖"
            lines.append(f"  {emoji} {p[1]}({p[0]})")
            lines.append(f"     {p[2]}股, 成本¥{float(p[3]):.4f}, "
                         f"现价¥{float(p[4]):.4f}")
            lines.append(f"     市值¥{_fmt_money(p[5])}, "
                         f"盈亏¥{_fmt_money(p[6])}({_fmt_pct(pnl_pct)})")
    else:
        lines.append("📦 当前空仓")

    lines.append("")
    lines.append("— 模拟盘 · 仅供参考，不构成投资建议 —")

    return "\n".join(lines)


def generate_nav_chart(account_id: int = 1) -> str:
    """
    生成净值曲线图，保存到 output/nav_chart.png
    返回文件路径
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT trade_date, total_value, cumulative_return "
                "FROM sim_daily_nav WHERE account_id = %s ORDER BY trade_date",
                (account_id,))
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return ""

    dates = [r[0] for r in rows]
    values = [float(r[1]) for r in rows]
    returns = [float(r[2]) * 100 for r in rows]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

    ax1.plot(dates, values, "b-", linewidth=1.5)
    ax1.axhline(100000, color="gray", linestyle="--", alpha=0.5)
    ax1.set_ylabel("Total Value (¥)")
    ax1.set_title("Simulated Portfolio NAV")
    ax1.grid(True, alpha=0.3)

    ax2.fill_between(dates, returns, 0,
                     where=[r >= 0 for r in returns], color="green", alpha=0.3)
    ax2.fill_between(dates, returns, 0,
                     where=[r < 0 for r in returns], color="red", alpha=0.3)
    ax2.plot(dates, returns, "k-", linewidth=1)
    ax2.set_ylabel("Cumulative Return (%)")
    ax2.set_xlabel("Date")
    ax2.grid(True, alpha=0.3)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    fig.autofmt_xdate()
    plt.tight_layout()

    path = os.path.join(OUTPUT_DIR, "nav_chart.png")
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


if __name__ == "__main__":
    report = generate_daily_report()
    print(report)
    chart = generate_nav_chart()
    if chart:
        print(f"\n净值曲线已保存: {chart}")
