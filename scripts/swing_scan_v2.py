"""修复版波段扫描 - 正确解析腾讯K线数据"""
import urllib.request
import json
import sqlite3
import datetime

DB_PATH = 'data/sim_live_mirror.db'

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
    ("sh600585", "海螺水泥"), ("sh600019", "宝钢股份"),
    ("sh600690", "海尔智家"), ("sz000002", "万科A"),
    ("sh601857", "中国石油"), ("sh601006", "大秦铁路"),
    ("sh600009", "上海机场"), ("sh601919", "中远海控"),
    ("sh600276", "恒瑞医药"), ("sz000538", "云南白药"),
    ("sh600085", "同仁堂"), ("sh601985", "中国核电"),
    ("sh600011", "华能国际"), ("sh601225", "陕西煤业"),
    ("sz002415", "海康威视"), ("sh601899", "紫金矿业"),
    ("sh601012", "隆基绿能"), ("sz300750", "宁德时代"),
    ("sh600030", "中信证券"), ("sh601688", "华泰证券"),
    ("sh600048", "保利发展"), ("sh600104", "上汽集团"),
    ("sz000001", "平安银行"), ("sh601009", "南京银行"),
    ("sh601169", "北京银行"), ("sh601328", "交通银行"),
    ("sh600016", "民生银行"),
]

COMMISSION_RATE = 0.00025  # 万2.5
STAMP_TAX_RATE = 0.0005    # 万5（仅卖出）

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
            'open': float(vals[5]), 'high': float(vals[33]), 'low': float(vals[34]),
            'change_pct': float(vals[32]),
            'volume': int(vals[6]) if vals[6] else 0,
            'amount': float(vals[37]) if vals[37] else 0,
            'turnover_rate': float(vals[38]) if vals[38] else 0,
            'pe_ttm': float(vals[39]) if vals[39] else 0,
            'pb': float(vals[46]) if vals[46] else 0,
            'amplitude': float(vals[49]) if vals[49] else 0,
        }
    except Exception as e:
        return None

def get_kline(code, days=40):
    """获取日K线 - 正确解析腾讯API格式"""
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode('utf-8'))
        # 腾讯API返回的数据结构: data -> {code_without_prefix} -> day
        # 例如 sh600036 -> 600036
        code_num = code.replace('sh', '').replace('sz', '')
        days_data = data.get('data', {}).get(code_num, {}).get('day', [])
        if not days_data:
            days_data = data.get('data', {}).get(code_num, {}).get('qfqday', [])
        klines = []
        for d in days_data:
            klines.append({
                'date': d[0],
                'open': float(d[1]),
                'close': float(d[2]),
                'high': float(d[3]),
                'low': float(d[4]),
                'volume': float(d[5]),
            })
        return klines
    except Exception as e:
        return None

def calc_ma(prices, period):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def calc_macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return None
    ema_fast = closes[0]
    ema_slow = closes[0]
    ema_list = []
    for i in range(len(closes)):
        ema_fast = closes[i] * 2/(fast+1) + ema_fast * (1 - 2/(fast+1))
        ema_slow = closes[i] * 2/(slow+1) + ema_slow * (1 - 2/(slow+1))
        if i >= slow - 1:
            ema_list.append({'dif': ema_fast - ema_slow})
    if len(ema_list) < signal:
        return None
    dea = ema_list[0]['dif']
    for i in range(1, len(ema_list)):
        dea = ema_list[i]['dif'] * 2/(signal+1) + dea * (1 - 2/(signal+1))
    dif = ema_list[-1]['dif']
    macd_val = 2 * (dif - dea)
    return {'dif': dif, 'dea': dea, 'macd': macd_val}

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(-period, 0):
        change = closes[i] - closes[i-1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_commission(amount, is_buy=True):
    """计算手续费"""
    comm = amount * COMMISSION_RATE
    comm = max(comm, 5)  # 最低5元
    tax = 0
    if not is_buy:
        tax = amount * STAMP_TAX_RATE  # 卖出印花税
    return comm, tax

def scan_swing(code, name):
    """扫描单只股票，返回波段机会（含盈亏比计算）"""
    quote = get_quote(code)
    if not quote:
        return None
    
    klines = get_kline(code, 40)
    if not klines or len(klines) < 20:
        return None
    
    closes = [k['close'] for k in klines]
    highs = [k['high'] for k in klines]
    lows = [k['low'] for k in klines]
    volumes = [k['volume'] for k in klines]
    
    price = quote['price']
    change_pct = quote['change_pct']
    
    # 计算指标
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60)
    rsi = calc_rsi(closes, 6)
    macd = calc_macd(closes)
    
    if not all([ma5, ma10, ma20]):
        return None
    
    # 成交量分析
    avg_vol_5 = sum(volumes[-5:]) / 5
    avg_vol_20 = sum(volumes[-20:]) / 20
    vol_ratio = avg_vol_5 / avg_vol_20 if avg_vol_20 > 0 else 1
    
    # 近5日平均振幅
    recent_amps = []
    for i in range(-5, 0):
        amp = (highs[i] - lows[i]) / closes[i-1] * 100
        recent_amps.append(amp)
    avg_amp = sum(recent_amps) / len(recent_amps) if recent_amps else 0
    
    # 波动率过滤：振幅太小没操作空间
    if avg_amp < 1.5:
        return None
    
    # === 信号判断 ===
    signals = []
    entry_price = None
    target_price = None
    stop_loss = None
    holding_days = "1-2天"
    
    # 条件A: 缩量回踩MA10/MA20支撑
    near_ma10 = abs(price - ma10) / ma10
    near_ma20 = abs(price - ma20) / ma20
    
    if near_ma10 < 0.015 and vol_ratio < 0.8:
        signals.append(("A-缩量回踩MA10", f"价{price:.2f}≈MA10({ma10:.2f}), 量比{vol_ratio:.2f}"))
        entry_price = price
        # 目标: MA5或前高
        target_price = max(ma5, closes[-2]) * 1.01
        stop_loss = ma10 * 0.98
    
    if near_ma20 < 0.015 and vol_ratio < 0.8:
        signals.append(("A-缩量回踩MA20", f"价{price:.2f}≈MA20({ma20:.2f}), 量比{vol_ratio:.2f}"))
        if not entry_price:
            entry_price = price
            target_price = ma10 * 1.01
            stop_loss = ma20 * 0.98
    
    # 条件B: MACD金叉
    if macd and macd['dif'] > macd['dea'] and abs(macd['dif'] - macd['dea']) < 0.5:
        # 检查是否刚金叉
        prev_macd = calc_macd(closes[:-1])
        if prev_macd and prev_macd['dif'] <= prev_macd['dea']:
            signals.append(("B-MACD金叉", f"DIF={macd['dif']:.2f}, DEA={macd['dea']:.2f}"))
            if not entry_price:
                entry_price = price
                target_price = price * 1.03
                stop_loss = price * 0.98
    
    # 条件C: 连续下跌后缩量企稳
    if len(closes) >= 5:
        last_3_close = closes[-3:]
        if all(last_3_close[i] < last_3_close[i-1] for i in range(1, 3)):
            if vol_ratio < 0.7 and abs(change_pct) < 1.0:
                signals.append(("C-三连阴缩量企稳", f"3日跌{(last_3_close[0]-last_3_close[-1])/last_3_close[0]*100:.1f}%"))
                if not entry_price:
                    entry_price = price
                    target_price = ma5 * 1.01
                    stop_loss = min(lows[-3:]) * 0.99
    
    # 条件D: RSI超卖
    if rsi and rsi < 35:
        signals.append(("D-RSI超卖", f"RSI(6)={rsi:.1f}"))
        if not entry_price:
            entry_price = price
            target_price = price * 1.03
            stop_loss = price * 0.97
    
    if not signals:
        return None
    
    # 确定最终止损和目标
    if not target_price:
        target_price = price * 1.025
    if not stop_loss:
        stop_loss = price * 0.975
    
    # 计算盈亏比
    potential_gain = (target_price - entry_price) / entry_price * 100
    potential_loss = (entry_price - stop_loss) / entry_price * 100
    
    # 计算手续费
    buy_amount = entry_price * 100  # 1手
    buy_comm, _ = calc_commission(buy_amount, is_buy=True)
    sell_amount = target_price * 100
    sell_comm, sell_tax = calc_commission(sell_amount, is_buy=False)
    total_cost = buy_comm + sell_comm + sell_tax
    cost_pct = total_cost / buy_amount * 100
    
    # 净盈亏比
    net_gain_pct = potential_gain - cost_pct
    net_loss_pct = potential_loss + cost_pct
    risk_reward_ratio = net_gain_pct / net_loss_pct if net_loss_pct > 0 else 0
    
    return {
        'name': name, 'code': code,
        'price': entry_price, 'change_pct': change_pct,
        'ma5': round(ma5, 2), 'ma10': round(ma10, 2), 'ma20': round(ma20, 2),
        'rsi': round(rsi, 1) if rsi else None,
        'avg_amp': round(avg_amp, 1),
        'vol_ratio': round(vol_ratio, 2),
        'signals': signals,
        'entry': round(entry_price, 2),
        'target': round(target_price, 2),
        'stop': round(stop_loss, 2),
        'gain_pct': round(potential_gain, 2),
        'loss_pct': round(potential_loss, 2),
        'cost_pct': round(cost_pct, 3),
        'net_gain_pct': round(net_gain_pct, 2),
        'net_loss_pct': round(net_loss_pct, 2),
        'risk_reward': round(risk_reward_ratio, 2),
        'pe_ttm': quote['pe_ttm'],
        'pb': quote['pb'],
    }

# ========== 执行 ==========
print("=" * 65)
print("📡 稳定型股票短线波段扫描 (含盈亏比计算)")
print(f"扫描时间: 2026-07-10 盘中")
print("=" * 65)

results = []
for code, name in STABLE_POOL:
    result = scan_swing(code, name)
    if result:
        results.append(result)

# 按盈亏比排序
results.sort(key=lambda x: x['risk_reward'], reverse=True)

if not results:
    print("\n❌ 当前无符合条件的短线波段机会")
else:
    print(f"\n共扫描{len(STABLE_POOL)}只，发现{len(results)}只有机会\n")
    
    for i, r in enumerate(results):
        signals_str = " | ".join([s[0] for s in r['signals']])
        print(f"{'─' * 55}")
        print(f"  {i+1}. {r['name']}({r['code']})  现价{r['price']:.2f} 涨跌{r['change_pct']:+.2f}%")
        print(f"     技术面: MA5={r['ma5']} MA10={r['ma10']} MA20={r['ma20']} RSI={r['rsi']}")
        print(f"     量价: 振幅{r['avg_amp']}% 量比{r['vol_ratio']} PE={r['pe_ttm']} PB={r['pb']}")
        print(f"     信号: {signals_str}")
        print(f"     ──── 交易计划 ────")
        print(f"     入场: {r['entry']:.2f} | 目标: {r['target']:.2f} | 止损: {r['stop']:.2f}")
        print(f"     预期收益: +{r['gain_pct']}% | 预期亏损: -{r['loss_pct']}% | 手续费: {r['cost_pct']}%")
        print(f"     净盈亏比: {r['risk_reward']}:1")
        print(f"     建议持有: 1-2天")
    
    print(f"\n{'=' * 55}")
    print("📊 盈亏比 > 2:1 的标的适合波段操作")
    print("📊 盈亏比 1.5-2:1 的可关注，等待更好入场点")
    print("📊 盈亏比 < 1.5:1 的放弃")
    print("⚠️ 以上为量化筛选结果，仅供参考，不构成投资建议")

# 保存到数据库
try:
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS swing_scan_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date TEXT, stock_code TEXT, stock_name TEXT,
            price REAL, change_pct REAL, ma5 REAL, ma10 REAL, ma20 REAL,
            rsi REAL, avg_amp REAL, vol_ratio REAL,
            entry_price REAL, target_price REAL, stop_price REAL,
            gain_pct REAL, loss_pct REAL, cost_pct REAL,
            net_gain_pct REAL, net_loss_pct REAL, risk_reward REAL,
            signals TEXT, pe_ttm REAL, pb REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for r in results:
        c.execute("""
            INSERT INTO swing_scan_results 
            (scan_date, stock_code, stock_name, price, change_pct, ma5, ma10, ma20,
             rsi, avg_amp, vol_ratio, entry_price, target_price, stop_price,
             gain_pct, loss_pct, cost_pct, net_gain_pct, net_loss_pct, risk_reward,
             signals, pe_ttm, pb)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.date.today().isoformat(), r['code'], r['name'],
            r['price'], r['change_pct'], r['ma5'], r['ma10'], r['ma20'],
            r['rsi'], r['avg_amp'], r['vol_ratio'],
            r['entry'], r['target'], r['stop'],
            r['gain_pct'], r['loss_pct'], r['cost_pct'],
            r['net_gain_pct'], r['net_loss_pct'], r['risk_reward'],
            "; ".join([s[0] for s in r['signals']]), r['pe_ttm'], r['pb']
        ))
    db.commit()
    db.close()
    print(f"\n✅ 结果已保存到 swing_scan_results 表")
except Exception as e:
    print(f"\n⚠️ 保存失败: {e}")
