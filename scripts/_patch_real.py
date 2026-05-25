"""Patch daily_advisor: 加入实盘持仓建议"""
from pathlib import Path

f = Path('scripts/daily_advisor.py')
text = f.read_text(encoding='utf-8')

# 1. 在 load_config 后面加一个 load_real_positions
insert_after = "def load_webhook():"
real_func = '''def load_real_positions():
    """加载实盘持仓 (config_real.yaml)"""
    path = ROOT / "config_real.yaml"
    if not path.exists():
        return None, []
    import yaml
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    account = data.get('account', {})
    positions = data.get('positions', [])
    return account, positions


'''

text = text.replace(insert_after, real_func + insert_after)

# 2. 在 gen_pre_market 开头加入实盘部分
old_pre = '''def gen_pre_market(positions, rules, cfg, auto_cfg):
    """盘前建议 (8:30-9:15)"""
    today = date.today().strftime('%m/%d')
    lines = [f"☀️ 盘前操作建议 ({today})", "=" * 40]'''

new_pre = '''def gen_real_advice(phase='pre'):
    """生成实盘专属建议"""
    real_acc, real_pos = load_real_positions()
    if not real_pos:
        return ""
    
    lines = ["", "━" * 40, "💼 【实盘操作建议】", "━" * 40]
    
    codes = [p['code'] for p in real_pos]
    rt = get_sina_prices(codes)
    
    # 实盘持仓状态
    total_mv = 0
    total_pnl = 0
    for p in real_pos:
        code = p['code']
        cost = p['avg_cost']
        qty = p['quantity']
        if code in rt:
            price = rt[code]['price']
            pnl = (price - cost) * qty
            pnl_pct = (price - cost) / cost * 100
            total_mv += price * qty
            total_pnl += pnl
            pct_today = rt[code]['pct']
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"  {emoji} {code} {p['name']:6s} {qty}股 成本{cost:.3f} 现价{price:.3f} 今日{pct_today:+.1f}% 浮盈{pnl:+.0f}({pnl_pct:+.1f}%)")
    
    cash = real_acc.get('cash', 0)
    total = cash + total_mv
    init = real_acc.get('initial_capital', 25000)
    lines.append(f"  📊 总资产 ¥{total:,.0f} | 现金 ¥{cash:,.0f} | 仓位 {total_mv/total*100:.0f}% | 总收益 {(total-init)/init*100:+.2f}%")
    
    # 实盘操作建议
    lines.append("")
    lines.append("📝 实盘操作建议:")
    
    for p in real_pos:
        code = p['code']
        cost = p['avg_cost']
        qty = p['quantity']
        if code not in rt:
            continue
        price = rt[code]['price']
        pnl_pct = (price - cost) / cost * 100
        
        # 止损线
        stop_8 = cost * 0.92
        
        if price <= stop_8:
            lines.append(f"  🚨 {p['name']}: 已触止损线(¥{stop_8:.2f})！建议止损卖出")
        elif pnl_pct >= 15:
            lines.append(f"  🎯 {p['name']}: 盈利{pnl_pct:+.1f}%达止盈①，建议卖半仓({qty//2}股)")
        elif pnl_pct >= 25:
            lines.append(f"  🎯 {p['name']}: 盈利{pnl_pct:+.1f}%达止盈②，建议清仓")
        elif pnl_pct < -5:
            lines.append(f"  ⚠️ {p['name']}: 亏损{pnl_pct:.1f}%，关注止损线¥{stop_8:.2f}，跌破则卖")
        elif pnl_pct > 5:
            lines.append(f"  📈 {p['name']}: 盈利{pnl_pct:+.1f}%，可上移止损至成本价(保本止损)")
        else:
            lines.append(f"  ✅ {p['name']}: 持仓正常，继续持有")
    
    # 加仓建议
    if cash > 5000 and total_mv / total < 0.5:
        lines.append(f"  💰 可用资金 ¥{cash:,.0f}，仓位偏低({total_mv/total*100:.0f}%)，可关注触发信号加仓")
    
    return '\\n'.join(lines)


def gen_pre_market(positions, rules, cfg, auto_cfg):
    """盘前建议 (8:30-9:15)"""
    today = date.today().strftime('%m/%d')
    lines = [f"☀️ 盘前操作建议 ({today})", "=" * 40]'''

text = text.replace(old_pre, new_pre)

# 3. 在每个 phase 的输出后面追加实盘建议
# 修改 main 里的 content 生成逻辑
old_main = '''    content = generators[phase]()
    print(content)'''

new_main = '''    content = generators[phase]()
    # 追加实盘建议
    real_advice = gen_real_advice(phase)
    if real_advice:
        content += real_advice
    print(content)'''

text = text.replace(old_main, new_main)

f.write_text(text, encoding='utf-8')
print("✓ Patched")
