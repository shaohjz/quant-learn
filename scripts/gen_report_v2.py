#!/usr/bin/env python3
"""
生成2026-07-03的复盘报告（最近交易日）
"""
import sqlite3
from datetime import datetime
from pathlib import Path

def generate_report():
    conn = sqlite3.connect('data/sim_live_mirror.db')
    conn.row_factory = sqlite3.Row
    
    # 使用最近有数据的交易日
    trade_date = '2026-07-03'
    
    # 获取账户信息
    account = conn.execute('SELECT * FROM sim_account WHERE id = 1').fetchone()
    
    # 获取最近交易日NAV
    nav = conn.execute(
        'SELECT * FROM sim_daily_nav WHERE account_id = 1 AND trade_date = ? ORDER BY created_at DESC LIMIT 1',
        (trade_date,)
    ).fetchone()
    
    # 获取前一交易日NAV
    nav_prev = conn.execute(
        'SELECT * FROM sim_daily_nav WHERE account_id = 1 AND trade_date < ? ORDER BY trade_date DESC LIMIT 1',
        (trade_date,)
    ).fetchone()
    
    # 获取持仓
    positions = conn.execute('SELECT * FROM sim_positions WHERE account_id = 1').fetchall()
    
    # 获取当日交易
    trades = conn.execute(
        'SELECT * FROM sim_trades WHERE account_id = 1 AND trade_date = ?',
        (trade_date,)
    ).fetchall()
    
    conn.close()
    
    # 构建企业微信Markdown格式报告
    lines = []
    lines.append(f"## 📊 量化模拟盘复盘 - {trade_date}")
    lines.append("")
    
    # 账户概况
    lines.append("**💰 账户概况**")
    if account:
        lines.append(f"- 初始资金: `{account['initial_cash']:.2f}`")
        lines.append(f"- 当前总值: `{account['total_value']:.2f}`")
        lines.append(f"- 可用现金: `{account['cash']:.2f}`")
    lines.append("")
    
    # 今日收益
    lines.append("**📈 收益情况**")
    if nav:
        lines.append(f"- 总市值: `{nav['total_value']:.2f}`")
        lines.append(f"- 持仓市值: `{nav['market_value']:.2f}`")
        lines.append(f"- 现金: `{nav['cash']:.2f}`")
        lines.append(f"- 日收益率: `{nav['daily_return']:.4f}%`")
        lines.append(f"- 累计收益率: `{nav['cumulative_return']:.4f}%`")
        
        if nav_prev:
            pnl = nav['total_value'] - nav_prev['total_value']
            pnl_pct = (pnl / nav_prev['total_value']) * 100
            emoji = "📈" if pnl > 0 else "📉"
            lines.append(f"- 当日盈亏: {emoji} `{pnl:+.2f}` ({pnl_pct:+.2f}%)")
    lines.append("")
    
    # 持仓明细
    lines.append("**📋 持仓明细**")
    real_positions = [p for p in positions if not p['stock_code'].startswith('00000')]
    
    if real_positions:
        for pos in real_positions:
            pnl_emoji = "📈" if pos['pnl'] > 0 else "📉" if pos['pnl'] < 0 else "➡️"
            lines.append(f"\n**{pos['stock_name']}** ({pos['stock_code']})")
            lines.append(f"- 持仓: `{pos['quantity']}` 股 @ 成本 `{pos['avg_cost']:.2f}`")
            lines.append(f"- 现价: `{pos['current_price']:.2f}` | 市值: `{pos['market_value']:.2f}`")
            lines.append(f"- 盈亏: {pnl_emoji} `{pos['pnl']:+.2f}` (`{pos['pnl_pct']:+.2f}%`)")
            
            # 止损检查
            if pos['trailing_stop_price']:
                stop_distance = ((pos['current_price'] - pos['trailing_stop_price']) / pos['current_price']) * 100
                if stop_distance < 5:
                    lines.append(f"- ⚠️ 接近止损: 止损价 `{pos['trailing_stop_price']:.2f}` (距离 {stop_distance:.1f}%)")
    else:
        lines.append("无真实持仓")
    lines.append("")
    
    # 当日交易
    lines.append("**🔄 当日交易**")
    real_trades = [t for t in trades if not t['stock_code'].startswith('00000')]
    
    if real_trades:
        for trade in real_trades:
            direction_emoji = "🟢" if trade['direction'] == 'BUY' else "🔴"
            lines.append(f"\n{direction_emoji} **{trade['direction']}** {trade['stock_name']} ({trade['stock_code']})")
            lines.append(f"- 价格: `{trade['price']:.2f}` | 数量: `{trade['quantity']}` 股")
            lines.append(f"- 金额: `{trade['amount']:.2f}`")
            if trade['signal_reason']:
                lines.append(f"- 信号: {trade['signal_reason']}")
    else:
        lines.append("当日无真实交易")
    lines.append("")
    
    # 风险提示
    lines.append("**⚠️ 风险提示**")
    risks = []
    for pos in real_positions:
        if pos['pnl_pct'] < -5:
            risks.append(f"- ❌ {pos['stock_name']} 浮亏 `{pos['pnl_pct']:.2f}%`，建议止损")
        if pos['trailing_stop_price'] and pos['current_price'] <= pos['trailing_stop_price'] * 1.02:
            risks.append(f"- ⚠️ {pos['stock_name']} 接近止损价，当前 `{pos['current_price']:.2f}` vs 止损 `{pos['trailing_stop_price']:.2f}`")
    
    if risks:
        lines.extend(risks)
    else:
        lines.append("暂无风险提示")
    lines.append("")
    
    lines.append("---")
    lines.append(f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    
    return "\n".join(lines)

if __name__ == '__main__':
    report = generate_report()
    print(report)
    
    # 保存到文件
    output_path = Path("docs/reviews/2026-07-03-auto.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding='utf-8')
    print(f"\n✅ 报告已保存: {output_path}")
