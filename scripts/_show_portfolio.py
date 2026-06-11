"""查看模拟账户持仓 + 今日实时行情"""
import sys
sys.path.insert(0, '.')
import requests, re
from sim.portfolio import fetch_account, fetch_positions, learn_account_id, real_account_id

def get_sina_prices(codes):
    """新浪实时行情"""
    sina_codes = []
    for c in codes:
        if c.startswith(('60', '68', '11', '12', '5')):
            sina_codes.append('sh' + c)
        else:
            sina_codes.append('sz' + c)
    url = 'https://hq.sinajs.cn/list=' + ','.join(sina_codes)
    headers = {'Referer': 'https://finance.sina.com.cn'}
    r = requests.get(url, headers=headers, timeout=10)
    r.encoding = 'gbk'
    prices = {}
    for line in r.text.strip().split('\n'):
        m = re.search(r'hq_str_(s[hz])(\d+)="(.+?)"', line)
        if m:
            code = m.group(2)
            parts = m.group(3).split(',')
            prices[code] = {
                'name': parts[0],
                'price': float(parts[3]),
                'yclose': float(parts[2]),
                'open': float(parts[1]),
                'high': float(parts[4]),
                'low': float(parts[5]),
                'pct': (float(parts[3]) - float(parts[2])) / float(parts[2]) * 100 if float(parts[2]) > 0 else 0
            }
    return prices

def show_account(acc_id, label):
    acc = fetch_account(acc_id)
    positions = fetch_positions(acc_id)
    
    if not acc:
        print(f"\n{'='*50}\n{label}: 账户不存在\n")
        return
    
    codes = [p['stock_code'] for p in positions]
    rt = get_sina_prices(codes) if codes else {}
    
    print(f"\n{'='*50}")
    print(f"📊 {label} (id={acc_id})")
    print(f"  💰 现金: ¥{acc['cash']:,.2f}")
    print(f"  📈 总值: ¥{acc['total_value']:,.2f}")
    print(f"{'='*50}")
    
    if not positions:
        print("  (空仓)")
        return
    
    total_mv = 0
    total_pnl = 0
    print(f"  {'代码':<8} {'名称':<8} {'数量':>5} {'成本':>7} {'现价':>7} {'涨跌':>7} {'浮盈':>8} {'盈亏%':>7}")
    print(f"  {'-'*70}")
    
    for p in positions:
        code = p['stock_code']
        qty = p['quantity']
        cost = p['avg_cost']
        
        # 用实时价
        if code in rt:
            cur = rt[code]['price']
            day_pct = rt[code]['pct']
        else:
            cur = p['current_price'] or cost
            day_pct = 0
        
        mv = cur * qty
        pnl = (cur - cost) * qty
        pnl_pct = (cur - cost) / cost * 100 if cost > 0 else 0
        total_mv += mv
        total_pnl += pnl
        
        pnl_icon = "🟢" if pnl >= 0 else "🔴"
        day_icon = "↑" if day_pct > 0 else ("↓" if day_pct < 0 else "→")
        
        print(f"  {code:<8} {p['stock_name']:<8} {qty:>5} "
              f"{cost:>7.3f} {cur:>7.3f} {day_icon}{day_pct:>+5.1f}% "
              f"{pnl_icon}{pnl:>+8.0f} {pnl_pct:>+6.1f}%")
    
    print(f"  {'-'*70}")
    total_asset = acc['cash'] + total_mv
    total_return = (total_asset - 100000) / 100000 * 100
    print(f"  持仓市值: ¥{total_mv:,.0f} | 浮盈合计: ¥{total_pnl:+,.0f}")
    print(f"  总资产: ¥{total_asset:,.0f} | 总收益率: {total_return:+.2f}%")


# 两个账户都看
show_account(learn_account_id(), "学习账户 (live_mirror·自动交易)")
show_account(real_account_id(), "真实账户 (real_portfolio·仅告警)")
