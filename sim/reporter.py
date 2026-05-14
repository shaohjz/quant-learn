"""
sim/reporter.py
报告生成器 — 生成每日模拟盘报告 + 净值曲线图（SQLite 版）
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
    """生成每日模拟盘报告（纯文本/Markdown）"""
    trade_date = trade_date or Date.today()
    conn = get_conn()
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT account_name, initial_cash, cash, total_value "
            "FROM sim_account WHERE id = ?", (account_id,))
        acct = cur.fetchone()

        cur.execute(
            "SELECT direction, stock_code, stock_name, price, quantity, "
            "amount, commission, tax, signal_reason, broker "
            "FROM sim_trades WHERE account_id = ? AND trade_date = ? "
            "ORDER BY id", (account_id, str(trade_date)))
        trades = cur.fetchall()

        cur.execute(
            "SELECT stock_code, stock_name, quantity, avg_cost, "
            "current_price, market_value, pnl, pnl_pct "
            "FROM sim_positions WHERE account_id = ? AND quantity > 0",
            (account_id,))
        positions = cur.fetchall()

        cur.execute(
            "SELECT total_value, cash, market_value, daily_return, "
            "cumulative_return, max_drawdown "
            "FROM sim_daily_nav WHERE account_id = ? AND trade_date = ?",
            (account_id, str(trade_date)))
        nav = cur.fetchone()
    finally:
        conn.close()

    lines = []
    lines.append(f"📊 模拟盘日报 | {trade_date}")
    lines.append("=" * 36)

    # 账户概况
    if acct:
        initial = float(acct["initial_cash"])
        cash = float(acct["cash"])
        total = float(acct["total_value"])
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
        lines.append(f"  日收益率: {_fmt_pct(nav['daily_return'])}")
        lines.append(f"  累计收益: {_fmt_pct(nav['cumulative_return'])}")
        mdd = nav["max_drawdown"]
        lines.append(f"  最大回撤: {_fmt_pct(-abs(float(mdd)) if mdd else 0)}")

    # 今日信号
    if signals:
        lines.append("")
        lines.append("🎯 今日信号")
        for s in signals:
            emoji = "🟢" if s["signal"] == "BUY" else "🔴" if s["signal"] == "SELL" else "⚪"
            lines.append(f"  {emoji} {s['name']}({s['code']}): {s['signal']}")
            lines.append(f"     价格: ¥{s['price']:.2f}")
            lines.append(f"     原因: {', '.join(s['reasons'])}")
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
            direction = t["direction"]
            emoji = "🟢买入" if direction == "BUY" else "🔴卖出"
            broker_tag = "" if (t["broker"] or "sim") == "sim" else f" [{t['broker']}]"
            lines.append(f"  {emoji}{broker_tag} {t['stock_name']}({t['stock_code']})")
            lines.append(f"     {t['quantity']}股 × ¥{float(t['price']):.4f} = ¥{_fmt_money(t['amount'])}")
            fee_parts = [f"佣金¥{float(t['commission']):.2f}"]
            if t["tax"] and float(t["tax"]) > 0:
                fee_parts.append(f"印花税¥{float(t['tax']):.2f}")
            lines.append(f"     费用: {' + '.join(fee_parts)}")
            if t["signal_reason"]:
                lines.append(f"     信号: {t['signal_reason']}")
    else:
        lines.append("")
        lines.append("📋 今日无交易")

    # 当前持仓
    lines.append("")
    if positions:
        lines.append("📦 当前持仓")
        for p in positions:
            pnl_pct = float(p["pnl_pct"]) if p["pnl_pct"] else 0
            emoji = "📈" if pnl_pct > 0 else "📉" if pnl_pct < 0 else "➖"
            lines.append(f"  {emoji} {p['stock_name']}({p['stock_code']})")
            lines.append(f"     {p['quantity']}股, 成本¥{float(p['avg_cost']):.4f}, "
                         f"现价¥{float(p['current_price']):.4f}")
            lines.append(f"     市值¥{_fmt_money(p['market_value'])}, "
                         f"盈亏¥{_fmt_money(p['pnl'])}({_fmt_pct(pnl_pct)})")
    else:
        lines.append("📦 当前空仓")

    lines.append("")
    lines.append("— 模拟盘 · 仅供参考，不构成投资建议 —")

    return "\n".join(lines)


def generate_nav_chart(account_id: int = 1) -> str:
    """生成净值曲线图，保存到 output/nav_chart.png"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT trade_date, total_value, cumulative_return "
            "FROM sim_daily_nav WHERE account_id = ? ORDER BY trade_date",
            (account_id,))
        rows = cur.fetchall()

        # 获取初始资金作为基准线
        cur.execute("SELECT initial_cash FROM sim_account WHERE id = ?", (account_id,))
        acct_row = cur.fetchone()
        initial_cash = float(acct_row["initial_cash"]) if acct_row else 20000.0
    finally:
        conn.close()

    if not rows:
        return ""

    from datetime import datetime as _dt
    dates = []
    for r in rows:
        d = r["trade_date"]
        if isinstance(d, str):
            dates.append(_dt.strptime(d, "%Y-%m-%d").date())
        else:
            dates.append(d)
    values = [float(r["total_value"]) for r in rows]
    returns = [float(r["cumulative_return"]) * 100 for r in rows]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

    ax1.plot(dates, values, "b-", linewidth=1.5)
    ax1.axhline(initial_cash, color="gray", linestyle="--", alpha=0.5)
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
