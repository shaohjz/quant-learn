import sqlite3, os, json, urllib.request, urllib.parse
from datetime import datetime, date

sim_db = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim.db'
lm_db = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db'
pm_db = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\pm.db'

today = '2026-06-16'

# ---- Fetch real-time prices for holdings ----
def fetch_sina_price(stock_code):
    """Fetch realtime price from Sina API"""
    # Convert code to sina format
    if stock_code.startswith('6'):
        sina_code = f'sh{stock_code}'
    elif stock_code.startswith('0') or stock_code.startswith('3'):
        sina_code = f'sz{stock_code}'
    else:
        return None
    
    url = f'https://hq.sinajs.cn/list={sina_code}'
    try:
        req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn'})
        resp = urllib.request.urlopen(req, timeout=5)
        content = resp.read().decode('gbk')
        # Parse: var hq_str_sh600036="平安银行,12.34,12.35,..."
        if 'hq_str_' in content:
            data = content.split('"')[1].split(',')
            if len(data) > 3:
                name = data[0]
                cur_price = float(data[3]) if data[3] else 0
                open_price = float(data[1]) if data[1] else 0
                yest_close = float(data[2]) if data[2] else 0
                return {
                    'name': name,
                    'cur_price': cur_price,
                    'open': open_price,
                    'yest_close': yest_close,
                    'change_pct': (cur_price - yest_close) / yest_close * 100 if yest_close else 0
                }
    except Exception as e:
        print(f'  Error fetching {stock_code}: {e}')
    return None

# ---- sim.db analysis ----
print('=== 模拟盘日报:', today, '===\n')
print('数据来源: sim.db (活跃模拟账户)')
print('注意: sim_live_mirror.db 已从备份恢复，包含2026-06-02的历史数据\n')

conn = sqlite3.connect(sim_db)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

cursor.execute("SELECT * FROM sim_account")
acct = cursor.fetchone()
print('【账户概况】')
print(f'  账户名: {acct["account_name"]}')
print(f'  初始资金: {acct["initial_cash"]:.0f}')
print(f'  可用现金: {acct["cash"]:.2f}')
print(f'  总市值(记录): {acct["total_value"]:.2f}')
print(f'  最后更新: {acct["updated_at"]}')

cursor.execute("SELECT * FROM sim_positions")
positions = cursor.fetchall()
print(f'\n【持仓明细】 ({len(positions)} 只)')

total_market_value = 0
total_pnl = 0
position_details = []

for p in positions:
    d = dict(p)
    stock_code = d['stock_code']
    
    # Try to fetch real price
    price_data = fetch_sina_price(stock_code)
    
    if price_data and price_data['cur_price'] > 0:
        cur_price = price_data['cur_price']
        change_pct = price_data['change_pct']
        stock_name = price_data['name']
        price_source = '实时'
    else:
        cur_price = d.get('current_price', 0) or 0
        change_pct = None
        stock_name = d.get('stock_name', '?')
        price_source = 'DB记录'
    
    avg_cost = d.get('avg_cost', 0) or 0
    qty = d.get('quantity', 0) or 0
    market_value = cur_price * qty
    pnl = (cur_price - avg_cost) * qty
    pnl_pct = (cur_price - avg_cost) / avg_cost if avg_cost else 0
    
    stop_loss_price = avg_cost * 0.92  # -8%
    take_profit_price = avg_cost * 1.15  # +15%
    
    stop_triggered = cur_price <= stop_loss_price
    tp_triggered = cur_price >= take_profit_price
    
    total_market_value += market_value
    total_pnl += pnl
    
    detail = {
        'code': stock_code,
        'name': stock_name,
        'qty': qty,
        'avg_cost': avg_cost,
        'cur_price': cur_price,
        'price_source': price_source,
        'market_value': market_value,
        'pnl': pnl,
        'pnl_pct': pnl_pct,
        'stop_loss_price': stop_loss_price,
        'stop_triggered': stop_triggered,
        'tp_triggered': tp_triggered,
        'change_pct': change_pct
    }
    position_details.append(detail)
    
    print(f'  {stock_code} {stock_name}:')
    print(f'    持仓: {qty}股, 成本={avg_cost:.2f}, 现价={cur_price:.2f} ({price_source})')
    if change_pct is not None:
        print(f'    今日涨跌: {change_pct:+.2f}%')
    print(f'    市值: {market_value:.0f}, 盈亏: {pnl:+.2f} ({pnl_pct*100:+.2f}%)')
    print(f'    止损线: {stop_loss_price:.2f} (触发={stop_triggered}), 止盈线: {take_profit_price:.2f} (触发={tp_triggered})')

total_assets = acct['cash'] + total_market_value
print(f'\n【资产汇总】')
print(f'  现金: {acct["cash"]:.2f}')
print(f'  持仓市值: {total_market_value:.2f}')
print(f'  总资产(计算): {total_assets:.2f}')
print(f'  总资产(DB): {acct["total_value"]:.2f}')
print(f'  累计盈亏: {total_pnl:+.2f}')
print(f'  累计收益率: {total_pnl/acct["initial_cash"]*100:+.2f}%')

# Check data issues
print(f'\n【数据异常检测】')
cursor.execute("SELECT COUNT(*) FROM sim_trades")
trade_count = cursor.fetchone()[0]
print(f'  sim_trades 记录数: {trade_count} (预期>0，当前持仓应有对应交易记录)')

if len(positions) == 1 and positions[0]['stock_name'] == 'TestLoss':
    print(f'  ⚠️ 持仓含测试脏数据: stock_name="TestLoss" (000001应为平安银行)')

conn.close()

# ---- sim_live_mirror.db analysis ----
print(f'\n【sim_live_mirror.db 状态】(历史数据，最后更新 2026-06-02)')
conn = sqlite3.connect(lm_db)
cursor = conn.cursor()
cursor.execute("SELECT cash, total_value, updated_at FROM sim_account ORDER BY id DESC LIMIT 2")
for r in cursor.fetchall():
    print(f'  账户: cash={r[0]:.2f}, total_value={r[1]:.2f}, updated={r[2]}')

cursor.execute("SELECT stock_code, stock_name, quantity, avg_cost, current_price, pnl_pct FROM sim_positions")
for r in cursor.fetchall():
    print(f'  持仓: {r[0]} {r[1]}: {r[2]}股, 成本={r[3]:.2f}, 现价={r[4]:.2f}, 盈亏={r[5]*100:.1f}%')
conn.close()

# Save report data as JSON for PM ticket creation
report_data = {
    'date': today,
    'account': dict(acct),
    'positions': position_details,
    'total_market_value': total_market_value,
    'total_pnl': total_pnl,
    'data_issues': []
}

if trade_count == 0:
    report_data['data_issues'].append('sim_trades为空，交易溯源断裂')
if len(positions) == 1 and positions[0]['stock_name'] == 'TestLoss':
    report_data['data_issues'].append('TestLoss脏数据未清理')

with open(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\daily_report_20260616.json', 'w') as f:
    json.dump(report_data, f, indent=2, ensure_ascii=False)

print('\n报告数据已保存至 data/daily_report_20260616.json')
