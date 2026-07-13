"""
短线波段扫描器 - 整合到量化模拟盘系统
包含：盈亏比计算、手续费、信号评分、操作建议
"""
import urllib.request
import json
import sqlite3
import datetime
import time

DB_PATH = 'data/sim_live_mirror.db'

# ========== 稳定型股票池 ==========
STABLE_POOL = [
    ("sh600036", "招商银行"), ("sh601166", "兴业银行"), ("sh600000", "浦发银行"),
    ("sh601318", "中国平安"), ("sh601628", "中国人寿"),
    ("sh600519", "贵州茅台"), ("sh600887", "伊利股份"), ("sh600809", "山西汾酒"),
    ("sh600900", "长江电力"), ("sh600886", "国投电力"),
    ("sz000333", "美的集团"), ("sz000651", "格力电器"),
    ("sh601088", "中国神华"), ("sh600188", "兖矿能源"),
    ("sh600941", "中国移动"),
    ("sh601390", "中国中铁"), ("sh601668", "中国建筑"),
    ("sh600028", "中国石化"), ("sh600025", "华能水电"),
    ("sh510050", "上证50ETF"), ("sh510300", "沪深300ETF"),
]

# 交易费用参数
COMMISSION_RATE = 0.00025  # 佣金万分之2.5
STAMP_TAX_RATE = 0.001     # 印花税千分之1（卖出）
MIN_COMMISSION = 5.0       # 最低佣金5元
MIN_PROFIT_RATIO = 0.008   # 最小目标收益 0.8%
MAX_LOSS_RATIO = 0.005     # 最大止损 0.5%
RISK_REWARD_MIN = 1.5      # 最小盈亏比 1.5

def get_quote(code):
    url = f'https://qt.gtimg.cn/q={code}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode('gbk')
        vals = data.split('"')[1].split('~')
        return {
            'name': vals[1], 'code': vals[2],
            'price': float(vals[3]), 'prev_close': float(vals[4]),
            'open': float(vals[5]), 'high': float(vals[33]),
            'low': float(vals[34]), 'change_pct': float(vals[32]),
            'volume': int(vals[6]) if vals[6] else 0,
            'amount': float(vals[37]) if vals[37] else 0,
            'turnover_rate': float(vals[38]) if vals[38] else 0,
            'pe_ttm': float(vals[39]) if vals[39] else 0,
            'pb': float(vals[46]) if vals[46] else 0,
        }
    except:
        return None

def get_kline(code, days=30):
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode('utf-8'))
        key = code
        days_data = data.get('data', {}).get(key, {}).get('day', [])
        if not days_data:
            days_data = data.get('data', {}).get(key, {}).get('qfqday', [])
        klines = []
        for d in days_data:
            klines.append({
                'date': d[0], 'open': float(d[1]), 'close': float(d[2]),
                'high': float(d[3]), 'low': float(d[4]), 'volume': float(d[5]),
            })
        return klines
    except:
        return None

def calc_ma(prices, period):
    if len(prices) < period: return None
    return sum(prices[-period:]) / period

def calc_commission(buy_price, sell_price, shares):
    """计算买卖总手续费"""
    buy_commission = max(buy_price * shares * COMMISSION_RATE, MIN_COMMISSION)
    sell_commission = max(sell_price * shares * COMMISSION_RATE, MIN_COMMISSION)
    stamp_tax = sell_price * shares * STAMP_TAX_RATE
    total = buy_commission + sell_commission + stamp_tax
    return total, buy_commission, sell_commission, stamp_tax

def scan_stock(code, name):
    """扫描单只股票，返回波段机会（含盈亏比计算）"""
    quote = get_quote(code)
    if not quote: return None
    
    klines = get_kline(code, 30)
    if not klines or len(klines) < 20: return None
    
    closes = [k['close'] for k in klines]
    volumes = [k['volume'] for k in klines]
    highs = [k['high'] for k in klines]
    lows = [k['low'] for k in klines]
    
    price = quote['price']
    change_pct = quote['change_pct']
    
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    if not all([ma5, ma10, ma20]): return None
    
    # 波动率
    recent_amps = []
    for i in range(max(1, len(klines)-10), len(klines)):
        amp = (highs[i] - lows[i]) / closes[i-1] * 100
        recent_amps.append(amp)
    avg_amp = sum(recent_amps) / len(recent_amps) if recent_amps else 0
    
    # 量比
    avg_vol_5 = sum(volumes[-5:]) / 5
    avg_vol_20 = sum(volumes[-20:]) / 20
    vol_ratio = avg_vol_5 / avg_vol_20 if avg_vol_20 > 0 else 1
    
    # 近5日最大涨幅/跌幅
    max_up_5 = 0
    max_down_5 = 0
    for i in range(-5, 0):
        d = (closes[i] - closes[i-1]) / closes[i-1] * 100
        if d > max_up_5: max_up_5 = d
        if d < max_down_5: max_down_5 = d
    
    signals = []
    
    # === 信号判断 ===
    # 1. 缩量回踩MA10
    if price <= ma10 * 1.015 and price >= ma10 * 0.985 and vol_ratio < 0.8:
        signals.append(("缩量回踩MA10", f"量比{vol_ratio:.2f}", 3))
    
    # 2. 缩量回踩MA20
    if price <= ma20 * 1.015 and price >= ma20 * 0.985 and vol_ratio < 0.8:
        signals.append(("缩量回踩MA20", f"量比{vol_ratio:.2f}", 3))
    
    # 3. 三连阴缩量企稳
    if len(closes) >= 5:
        last_3 = closes[-3:]
        if all(last_3[i] < last_3[i-1] for i in range(1, 3)) and vol_ratio < 0.7 and change_pct >= -1.0:
            signals.append(("三连阴缩量企稳", f"3日跌{(last_3[0]-last_3[-1])/last_3[0]*100:.1f}%", 4))
    
    # 4. MA5上穿MA10
    if len(closes) >= 12:
        ma5_prev = calc_ma(closes[:-1], 5)
        ma10_prev = calc_ma(closes[:-1], 10)
        if ma5_prev and ma10_prev and ma5_prev <= ma10_prev and ma5 > ma10:
            signals.append(("MA5上穿MA10", "金叉", 4))
    
    # 5. 回调缩量
    if change_pct < -1.5 and vol_ratio < 0.8:
        signals.append(("回调缩量", f"跌{change_pct:.1f}%", 2))
    
    # 6. 放量突破MA5
    if price > ma5 and change_pct > 1.0 and vol_ratio > 1.2:
        signals.append(("放量站上MA5", f"涨{change_pct:.1f}%", 2))
    
    if not signals: return None
    
    # === 盈亏比计算 ===
    score = sum(s[2] for s in signals)
    
    # 目标价：MA20（向上）或 近期高点
    recent_high = max(highs[-10:])
    target_price = max(ma20, recent_high) if price < ma20 else price * 1.02
    
    # 止损价：MA20（向下）或 近期低点
    recent_low = min(lows[-5:])
    stop_loss = min(ma20, recent_low) if price > ma20 else price * 0.98
    
    # 确保止损价合理
    if stop_loss >= price:
        stop_loss = price * 0.985
    
    # 计算盈亏比
    potential_profit = (target_price - price) / price
    potential_loss = (price - stop_loss) / price
    
    if potential_loss <= 0:
        return None
    
    risk_reward = potential_profit / potential_loss
    
    # 计算手续费影响
    test_shares = 100  # 假设100股
    fees, _, _, _ = calc_commission(price, target_price, test_shares)
    fee_ratio = fees / (price * test_shares)
    
    # 净收益
    net_profit_ratio = potential_profit - fee_ratio
    net_loss_ratio = potential_loss + fee_ratio
    
    net_risk_reward = net_profit_ratio / net_loss_ratio if net_loss_ratio > 0 else 0
    
    # 综合评分
    final_score = score
    if risk_reward >= 2.0: final_score += 2
    elif risk_reward >= 1.5: final_score += 1
    if avg_amp >= 2.0: final_score += 1  # 有波动空间
    if vol_ratio < 0.6: final_score += 1  # 极度缩量加分
    
    return {
        'name': name, 'code': code,
        'price': price, 'change_pct': change_pct,
        'ma5': round(ma5, 2), 'ma10': round(ma10, 2), 'ma20': round(ma20, 2),
        'avg_amp': round(avg_amp, 1), 'vol_ratio': round(vol_ratio, 2),
        'signals': signals, 'score': final_score,
        'target_price': round(target_price, 2),
        'stop_loss': round(stop_loss, 2),
        'potential_profit_pct': round(potential_profit * 100, 2),
        'potential_loss_pct': round(potential_loss * 100, 2),
        'risk_reward': round(risk_reward, 2),
        'net_risk_reward': round(net_risk_reward, 2),
        'fee_ratio': round(fee_ratio * 100, 3),
        'pe_ttm': quote['pe_ttm'], 'pb': quote['pb'],
    }

def get_current_positions():
    """获取当前模拟盘持仓"""
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    c.execute("""
        SELECT stock_code, stock_name, quantity, avg_cost, current_price, pnl_pct 
        FROM sim_positions WHERE quantity > 0 AND account_id = 1
    """)
    positions = [{'code': r[0], 'name': r[1], 'qty': r[2], 'cost': r[3], 'price': r[4], 'pnl_pct': r[5]} for r in c.fetchall()]
    c.execute("SELECT cash FROM sim_account WHERE id = 1")
    cash = c.fetchone()[0]
    db.close()
    return positions, cash

def get_account_summary():
    """获取账户概况"""
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    c.execute("SELECT total_value, cash FROM sim_account WHERE id = 1")
    total, cash = c.fetchone()
    c.execute("SELECT total_pnl FROM sim_daily_nav WHERE account_id = 1 ORDER BY id DESC LIMIT 1")
    total_pnl_pct = c.fetchone()[0] * 100
    db.close()
    return total, cash, total_pnl_pct

def save_to_db(results, scan_date):
    """保存扫描结果到数据库"""
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS swing_scan_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date TEXT, stock_code TEXT, stock_name TEXT,
            price REAL, change_pct REAL, score INTEGER,
            signals TEXT, ma20 REAL, stop_loss REAL, target_price REAL,
            risk_reward REAL, net_risk_reward REAL,
            pe_ttm REAL, pb REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for r in results:
        c.execute("""
            INSERT INTO swing_scan_results 
            (scan_date, stock_code, stock_name, price, change_pct, score, signals, 
             ma20, stop_loss, target_price, risk_reward, net_risk_reward, pe_ttm, pb)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            scan_date, r['code'], r['name'], r['price'], r['change_pct'],
            r['score'], "; ".join(f"{s[0]}" for s in r['signals']),
            r['ma20'], r['stop_loss'], r['target_price'],
            r['risk_reward'], r['net_risk_reward'], r['pe_ttm'], r['pb']
        ))
    db.commit()
    db.close()

# ========== 主流程 ==========
today = datetime.date.today().strftime("%Y-%m-%d")
print("=" * 60)
print(f"📡 短线波段扫描报告 - {today}")
print("=" * 60)

# 账户概况
total, cash, total_pnl = get_account_summary()
positions, cash_avail = get_current_positions()
print(f"\n📊 账户概况: 总资产{total:.2f} | 现金{cash_avail:.2f} | 累计收益{total_pnl:.2f}%")
print(f"📊 当前持仓: {len(positions)}只")
for p in positions:
    print(f"   {p['name']}({p['code']}) {p['qty']}股 @{p['cost']:.2f} 现价{p['price']:.2f} {p['pnl_pct']:+.2f}%")

# 扫描波段机会
print(f"\n🔄 扫描股票池 ({len(STABLE_POOL)}只)...")
results = []
for code, name in STABLE_POOL:
    time.sleep(0.3)
    try:
        r = scan_stock(code, name)
        if r:
            results.append(r)
    except:
        pass

results.sort(key=lambda x: x['score'], reverse=True)

# 保存结果
save_to_db(results, today)

# 输出报告
print(f"\n{'='*60}")
print(f"📡 波段机会扫描报告")
print(f"{'='*60}")

if not results:
    print("\n当前无符合条件的短线波段机会")
else:
    print(f"\n发现 {len(results)} 只有波段信号:")
    print(f"{'─'*60}")
    
    for i, r in enumerate(results[:8]):
        sigs = " | ".join(f"{s[0]}" for s in r['signals'])
        print(f"\n{i+1}. {r['name']}({r['code']})  现价{r['price']:.2f} {r['change_pct']:+.2f}%")
        print(f"   MA5={r['ma5']:.2f} MA10={r['ma10']:.2f} MA20={r['ma20']:.2f}")
        print(f"   信号: {sigs}")
        print(f"   目标: {r['target_price']:.2f}(+{r['potential_profit_pct']:.1f}%) | 止损: {r['stop_loss']:.2f}({r['potential_loss_pct']:.1f}%)")
        print(f"   盈亏比: {r['risk_reward']:.2f}(净{r['net_risk_reward']:.2f}) | 手续费{r['fee_ratio']:.3f}%")
        print(f"   评分: {'⭐' * (min(r['score'] // 2, 7))} ({r['score']}分)")
    
    # 操作建议
    print(f"\n{'='*60}")
    print("📋 操作建议")
    print(f"{'─'*60}")
    
    buy_list = [r for r in results if r['net_risk_reward'] >= 1.5 and r['score'] >= 5]
    watch_list = [r for r in results if r['net_risk_reward'] >= 1.0 and r['score'] >= 3]
    
    if buy_list:
        print(f"\n🟢 建议关注（盈亏比≥1.5，评分≥5）:")
        for r in buy_list:
            print(f"   {r['name']}({r['code']}) 现价{r['price']:.2f} → 目标{r['target_price']:.2f} / 止损{r['stop_loss']:.2f}")
            print(f"   盈亏比{r['risk_reward']:.2f} | 预期收益{r['potential_profit_pct']:.1f}% | 风险{r['potential_loss_pct']:.1f}%")
    else:
        print(f"\n当前无高确定性机会，建议观望")
    
    if watch_list and len(watch_list) > len(buy_list):
        print(f"\n👀 观察列表（盈亏比≥1.0，评分≥3）:")
        for r in watch_list:
            if r not in (buy_list if buy_list else []):
                print(f"   {r['name']}({r['code']}) 评分{r['score']} 盈亏比{r['risk_reward']:.2f}")

print(f"\n{'='*60}")
print(f"✅ 结果已保存到数据库 swing_scan_results 表")
print(f"⚠️ 以上为量化筛选结果，仅供参考，不构成投资建议")
