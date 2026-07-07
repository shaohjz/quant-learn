#!/usr/bin/env python3
"""
生成每日复盘报告并推送到企微群
"""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def get_latest_trade_date(conn, account_id=1):
    """Find the most recent trade date with NAV data.
    
    If today has NAV, use today. Otherwise (weekends/holidays), fall back
    to the most recent date that has NAV records.
    """
    row = conn.execute(
        'SELECT trade_date FROM sim_daily_nav WHERE account_id=? ORDER BY trade_date DESC LIMIT 1',
        (account_id,)
    ).fetchone()
    return row['trade_date'] if row else datetime.now().strftime('%Y-%m-%d')


def get_daily_summary():
    """获取每日复盘摘要"""
    conn = sqlite3.connect('data/sim_live_mirror.db')
    conn.row_factory = sqlite3.Row
    
    report_date = get_latest_trade_date(conn)
    today = datetime.now().strftime('%Y-%m-%d')
    is_non_trading_day = (report_date != today)
    
    # 获取账户信息
    account = conn.execute('SELECT * FROM sim_account WHERE id = 1').fetchone()
    
    # 获取最新交易日 NAV
    nav_today = conn.execute(
        'SELECT * FROM sim_daily_nav WHERE account_id = 1 AND trade_date = ? ORDER BY created_at DESC LIMIT 1',
        (report_date,)
    ).fetchone()
    
    # 获取前一交易日 NAV
    prev_date_row = conn.execute(
        'SELECT trade_date FROM sim_daily_nav WHERE account_id = 1 AND trade_date < ? ORDER BY trade_date DESC LIMIT 1',
        (report_date,)
    ).fetchone()
    prev_date = prev_date_row['trade_date'] if prev_date_row else None
    nav_yesterday = None
    if prev_date:
        nav_yesterday = conn.execute(
            'SELECT * FROM sim_daily_nav WHERE account_id = 1 AND trade_date = ? ORDER BY created_at DESC LIMIT 1',
            (prev_date,)
        ).fetchone()
    
    # 获取持仓
    positions = conn.execute('SELECT * FROM sim_positions WHERE account_id = 1').fetchall()
    
    # 获取最新交易日交易
    trades_today = conn.execute(
        'SELECT * FROM sim_trades WHERE account_id = 1 AND trade_date = ?',
        (report_date,)
    ).fetchall()
    
    conn.close()
    
    # 构建报告
    report_lines = []
    title_date = report_date
    if is_non_trading_day:
        report_lines.append(f"# 📊 量化模拟盘每日复盘 - {report_date}（非交易日，使用最新交易日数据）")
        report_lines.append("> ⚠️ 今日({today})为非交易日，以下为最近交易日 ({report_date}) 的数据")
    else:
        report_lines.append(f"# 📊 量化模拟盘每日复盘 - {report_date}")
    report_lines.append("")
    
    # 账户概况
    report_lines.append("## 💰 账户概况")
    if account:
        report_lines.append(f"- 初始资金: {account['initial_cash']:.2f}")
        report_lines.append(f"- 当前总值: {account['total_value']:.2f}")
        report_lines.append(f"- 可用现金: {account['cash']:.2f}")
    report_lines.append("")
    
    # 今日收益
    report_lines.append("## 📈 今日收益")
    if nav_today:
        report_lines.append(f"- 总市值: {nav_today['total_value']:.2f}")
        report_lines.append(f"- 市值: {nav_today['market_value']:.2f}")
        report_lines.append(f"- 现金: {nav_today['cash']:.2f}")
        report_lines.append(f"- 日收益率: {nav_today['daily_return']:.4f}%")
        report_lines.append(f"- 累计收益率: {nav_today['cumulative_return']:.4f}%")
        
        if nav_yesterday:
            pnl = nav_today['total_value'] - nav_yesterday['total_value']
            report_lines.append(f"- 今日盈亏: {pnl:+.2f}")
    report_lines.append("")
    
    # 持仓明细
    report_lines.append("## 📋 持仓明细")
    if positions:
        for pos in positions:
            report_lines.append(f"### {pos['stock_name']} ({pos['stock_code']})")
            report_lines.append(f"- 持仓: {pos['quantity']} 股")
            report_lines.append(f"- 成本价: {pos['avg_cost']:.2f}")
            report_lines.append(f"- 现价: {pos['current_price']:.2f}")
            report_lines.append(f"- 市值: {pos['market_value']:.2f}")
            report_lines.append(f"- 盈亏: {pos['pnl']:+.2f} ({pos['pnl_pct']:+.2f}%)")
            
            # 检查止损止盈
            if pos['trailing_stop_price']:
                report_lines.append(f"- 跟踪止损价: {pos['trailing_stop_price']:.2f}")
                if pos['current_price'] <= pos['trailing_stop_price']:
                    report_lines.append(f"  ⚠️ **已触发止损!**")
            report_lines.append("")
    
    # 最近交易日交易
    trade_label = f"## 🔄 交易日交易 ({report_date})" if is_non_trading_day else "## 🔄 今日交易"
    report_lines.append(trade_label)
    if trades_today:
        for trade in trades_today:
            report_lines.append(f"- {trade['direction']} {trade['stock_name']} ({trade['stock_code']})")
            report_lines.append(f"  - 价格: {trade['price']:.2f}, 数量: {trade['quantity']}")
            report_lines.append(f"  - 信号: {trade['signal_reason']}")
            report_lines.append("")
    else:
        report_lines.append("无交易")
        report_lines.append("")
    
    # 风险提示
    report_lines.append("## ⚠️ 风险提示")
    risk_found = False
    for pos in positions:
        if pos['pnl_pct'] < -5:
            report_lines.append(f"- {pos['stock_name']} 浮亏 {pos['pnl_pct']:.2f}%，注意止损")
            risk_found = True
        if pos['trailing_stop_price'] and pos['current_price'] <= pos['trailing_stop_price'] * 1.05:
            report_lines.append(f"- {pos['stock_name']} 接近止损价，当前价 {pos['current_price']:.2f}，止损价 {pos['trailing_stop_price']:.2f}")
            risk_found = True
    
    if not risk_found:
        report_lines.append("暂无风险")
    
    report_lines.append("")
    report_lines.append("---")
    report_lines.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    
    return "\n".join(report_lines)

if __name__ == '__main__':
    report = get_daily_summary()
    print(report)
    
    # 保存到文件
    today = datetime.now().strftime('%Y-%m-%d')
    report_path = Path(f"docs/reviews/{today}.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding='utf-8')
    print(f"\n✅ 报告已保存至: {report_path}")
