#!/usr/bin/env python3
"""生成简洁版日报推送到企微"""
import sqlite3
from datetime import datetime
from pathlib import Path

def gen_summary():
    conn = sqlite3.connect('data/sim_live_mirror.db')
    conn.row_factory = sqlite3.Row
    
    trade_date = '2026-07-03'
    
    # 获取NAV
    nav = conn.execute(
        'SELECT * FROM sim_daily_nav WHERE account_id=1 AND trade_date=? ORDER BY created_at DESC LIMIT 1',
        (trade_date,)
    ).fetchone()
    
    nav_prev = conn.execute(
        'SELECT * FROM sim_daily_nav WHERE account_id=1 AND trade_date<? ORDER BY trade_date DESC LIMIT 1',
        (trade_date,)
    ).fetchone()
    
    # 获取真实持仓（过滤测试股票）
    positions = conn.execute(
        'SELECT * FROM sim_positions WHERE account_id=1 AND stock_code NOT LIKE "00000%"'
    ).fetchall()
    
    # 获取真实交易
    trades = conn.execute(
        'SELECT * FROM sim_trades WHERE account_id=1 AND trade_date=? AND stock_code NOT LIKE "00000%"',
        (trade_date,)
    ).fetchall()
    
    conn.close()
    
    # 计算盈亏
    pnl = 0
    pnl_pct = 0
    if nav and nav_prev:
        pnl = nav['total_value'] - nav_prev['total_value']
        pnl_pct = (pnl / nav_prev['total_value']) * 100
    
    # 构建简洁报告
    lines = []
    lines.append(f"📊 **量化模拟盘复盘 {trade_date}**\n")
    
    # 核心指标
    lines.append("**💰 核心指标**")
    if nav:
        lines.append(f"- 总资产: `{nav['total_value']:.2f}`")
        lines.append(f"- 市值: `{nav['market_value']:.2f}` | 现金: `{nav['cash']:.2f}`")
        lines.append(f"- 日收益: `{nav['daily_return']:.2f}%` | 累计: `{nav['cumulative_return']:.2f}%`")
        if nav_prev:
            emoji = "📈" if pnl > 0 else "📉"
            lines.append(f"- 当日盈亏: {emoji} `{pnl:+.2f}` ({pnl_pct:+.2f}%)")
    lines.append("")
    
    # 持仓概览
    lines.append("**📋 持仓概览**")
    if positions:
        total_pnl = sum(p['pnl'] for p in positions)
        lines.append(f"- 持仓数: {len(positions)} | 总浮动盈亏: `{total_pnl:+.2f}`")
        for pos in positions:
            emoji = "📈" if pos['pnl'] > 0 else "📉"
            lines.append(f"- {pos['stock_name']}: {emoji} `{pos['pnl_pct']:+.2f}%` (成本`{pos['avg_cost']:.2f}`→现价`{pos['current_price']:.2f}`)")
    lines.append("")
    
    # 当日交易
    lines.append("**🔄 当日交易**")
    if trades:
        buy_count = len([t for t in trades if t['direction'] == 'BUY'])
        sell_count = len([t for t in trades if t['direction'] == 'SELL'])
        lines.append(f"- 交易笔数: 买入`{buy_count}`, 卖出`{sell_count}`")
        for trade in trades:
            direction = "买入" if trade['direction'] == 'BUY' else "卖出"
            lines.append(f"- {direction} {trade['stock_name']} `{trade['quantity']}`股 @ `{trade['price']:.2f}`")
    else:
        lines.append("- 无交易")
    lines.append("")
    
    # 风险提示
    lines.append("**⚠️ 关注事项**")
    risks = []
    
    # 检查接近止损
    for pos in positions:
        if pos['trailing_stop_price']:
            stop_dist = ((pos['current_price'] - pos['trailing_stop_price']) / pos['current_price']) * 100
            if stop_dist < 5:
                risks.append(f"- {pos['stock_name']} 接近止损 (距离`{stop_dist:.1f}%`)")
    
    # 检查浮亏
    for pos in positions:
        if pos['pnl_pct'] < -3:
            risks.append(f"- {pos['stock_name']} 浮亏`{pos['pnl_pct']:.2f}%`")
    
    if risks:
        lines.extend(risks)
    else:
        lines.append("- 无")
    lines.append("")
    
    lines.append("---")
    lines.append(f"生成时间: {datetime.now().strftime('%m-%d %H:%M')}")
    
    return "\n".join(lines)

if __name__ == '__main__':
    summary = gen_summary()
    print(summary)
    
    # 保存
    output_path = Path("docs/reviews/2026-07-03-summary.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(summary, encoding='utf-8')
    print(f"\n✅ 已保存: {output_path}")
    
    # 推送
    try:
        from scripts.wecom_webhook import push_markdown
        push_markdown(summary)
        print("✅ 已推送到企微群")
    except Exception as e:
        print(f"❌ 推送失败: {e}")
