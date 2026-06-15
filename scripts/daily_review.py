import sqlite3
import requests
import json
from datetime import datetime, date
import sys

# ===== 获取A股实时行情 (腾讯接口) =====
def get_tencent_price(stock_code):
    """使用腾讯接口获取实时行情，免费不封IP"""
    # 腾讯行情接口: https://qt.gtimg.cn/q=sh600519 或 sz000001
    if stock_code.startswith('6'):
        prefix = 'sh'
    else:
        prefix = 'sz'
    url = f"https://qt.gtimg.cn/q={prefix}{stock_code}"
    try:
        resp = requests.get(url, timeout=5)
        resp.encoding = 'gbk'
        text = resp.text
        # 解析格式: v_sz000001="1~平安银行~000001~12.34~..."
        if '~' in text:
            parts = text.split('~')
            if len(parts) > 30:
                name = parts[1]
                current_price = float(parts[3]) if parts[3] else 0
                open_price = float(parts[5]) if parts[5] else 0
                pre_close = float(parts[4]) if parts[4] else 0
                high = float(parts[33]) if len(parts) > 33 and parts[33] else 0
                low = float(parts[34]) if len(parts) > 34 and parts[34] else 0
                volume = int(parts[6]) if parts[6] else 0
                change_pct = ((current_price - pre_close) / pre_close * 100) if pre_close > 0 else 0
                return {
                    'name': name,
                    'current_price': current_price,
                    'pre_close': pre_close,
                    'open': open_price,
                    'high': high,
                    'low': low,
                    'change_pct': change_pct,
                    'volume': volume
                }
    except Exception as e:
        print(f"  获取行情失败: {e}", file=sys.stderr)
    return None

# ===== 主逻辑 =====
conn = sqlite3.connect('data/sim_live_mirror.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("=" * 60)
print("📊 量化模拟盘 - 每日复盘报告")
print(f"📅 日期: {date.today()}  生成时间: {datetime.now().strftime('%H:%M:%S')}")
print("=" * 60)

# 1. 账户概览
cursor.execute("SELECT * FROM sim_account WHERE id=1")
account = dict(cursor.fetchone())
initial_cash = account['initial_cash']
cash = account['cash']
total_value = account['total_value']
pnl_total = total_value - initial_cash
pnl_pct_total = (pnl_total / initial_cash * 100) if initial_cash > 0 else 0

print(f"\n【账户概览】")
print(f"  初始资金:   ¥{initial_cash:,.2f}")
print(f"  当前现金:   ¥{cash:,.2f}")
print(f"  总资产:     ¥{total_value:,.2f}")
print(f"  累计盈亏:   ¥{pnl_total:,.2f} ({pnl_pct_total:+.2f}%)")

# 2. 持仓分析
cursor.execute("SELECT * FROM sim_positions")
positions = [dict(r) for r in cursor.fetchall()]

print(f"\n【持仓分析】共 {len(positions)} 只持仓")
total_market_value = 0
total_position_pnl = 0
issues = []

for pos in positions:
    code = pos['stock_code']
    name = pos['stock_name']
    qty = pos['quantity']
    avg_cost = pos['avg_cost']
    current_price_db = pos['current_price']
    highest = pos['highest_price'] or current_price_db
    
    # 获取实时行情
    print(f"\n  🔍 正在获取 {name}({code}) 实时行情...")
    quote = get_tencent_price(code)
    
    if quote:
        real_price = quote['current_price']
        change_pct = quote['change_pct']
        day_high = quote['high']
        day_low = quote['low']
        
        # 更新数据库中的当前价格
        market_value = qty * real_price
        pnl = (real_price - avg_cost) * qty
        pnl_pct = (real_price - avg_cost) / avg_cost * 100
        total_market_value += market_value
        total_position_pnl += pnl
        
        # 检查止损
        stop_loss_pct = -0.1  # 默认10%止损
        if pnl_pct <= stop_loss_pct * 100:
            issues.append(f"⚠️ 止损触发: {name}({code}) 亏损 {pnl_pct:.2f}%，已超过止损线({stop_loss_pct*100:.0f}%)")
        
        # 检查止盈
        take_profit_pct = 0.2
        if pnl_pct >= take_profit_pct * 100:
            issues.append(f"🎯 止盈提醒: {name}({code}) 盈利 {pnl_pct:.2f}%，已达标止盈线({take_profit_pct*100:.0f}%)")
        
        print(f"  📌 {name}({code})")
        print(f"     持仓: {qty}股  成本: ¥{avg_cost:.2f}  现价: ¥{real_price:.2f} ({change_pct:+.2f}%)")
        print(f"     市值: ¥{market_value:,.2f}  盈亏: ¥{pnl:,.2f} ({pnl_pct:+.2f}%)")
        print(f"     今日区间: ¥{day_low:.2f} ~ ¥{day_high:.2f}")
        
        # 更新数据库
        new_highest = max(highest, day_high) if day_high > 0 else highest
        cursor.execute(
            "UPDATE sim_positions SET current_price=?, market_value=?, pnl=?, pnl_pct=?, highest_price=?, updated_at=? WHERE id=?",
            (real_price, market_value, pnl, pnl_pct/100, new_highest, datetime.now().isoformat(), pos['id'])
        )
    else:
        # 无法获取实时行情，使用DB数据
        market_value = pos['market_value']
        pnl = pos['pnl']
        pnl_pct = pos['pnl_pct'] * 100
        total_market_value += market_value
        total_position_pnl += pnl
        print(f"  📌 {name}({code}) [使用缓存数据]")
        print(f"     持仓: {qty}股  成本: ¥{avg_cost:.2f}  现价: ¥{current_price_db:.2f}")
        print(f"     市值: ¥{market_value:,.2f}  盈亏: ¥{pnl:,.2f} ({pnl_pct:+.2f}%)")
        issues.append(f"⚠️ 无法获取 {name}({code}) 实时行情，数据可能过期")

# 3. 保存更新
conn.commit()

# 4. 计算今日收益（如果有历史NAV）
cursor.execute("SELECT total_value FROM sim_daily_nav WHERE account_id=1 ORDER BY trade_date DESC LIMIT 1")
yesterday_nav = cursor.fetchone()
yesterday_value = yesterday_nav[0] if yesterday_nav else initial_cash

today_return = (total_value - yesterday_value) / yesterday_value * 100 if yesterday_value > 0 else 0

print(f"\n【今日收益】")
print(f"  总资产变动: ¥{total_value - yesterday_value:,.2f} ({today_return:+.2f}%)")
print(f"  持仓市值:   ¥{total_market_value:,.2f}")
print(f"  现金:       ¥{cash:,.2f}")

# 5. 问题汇总
print(f"\n【风险提示与待处理事项】")
if issues:
    for issue in issues:
        print(f"  {issue}")
else:
    print("  ✅ 暂无风险预警")

# 6. 写入今日NAV
try:
    cursor.execute(
        "INSERT OR REPLACE INTO sim_daily_nav (account_id, trade_date, total_value, cash, market_value, daily_return, cumulative_return, max_drawdown) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (1, date.today().isoformat(), total_value, cash, total_market_value, 
         today_return / 100,
         (total_value - initial_cash) / initial_cash,
         0.0)
    )
    conn.commit()
    print("\n  ✅ 今日NAV已记录")
except Exception as e:
    print(f"\n  ⚠️ NAV记录失败: {e}")

conn.close()

print("\n" + "=" * 60)
print("复盘完成")
print("=" * 60)
