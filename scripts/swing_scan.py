"""扫描稳定型股票的短线波段机会"""
import urllib.request
import json
import sqlite3

# ========== 稳定型股票池（低波动蓝筹/ETF） ==========
STABLE_POOL = [
    # 银行
    ("sh600036", "招商银行"), ("sh601166", "兴业银行"), ("sh600000", "浦发银行"),
    # 保险
    ("sh601318", "中国平安"), ("sh601628", "中国人寿"),
    # 券商
    ("sh600030", "中信证券"), ("sh601211", "国泰君安"), ("sh600837", "海通证券"),
    # 消费
    ("sh600519", "贵州茅台"), ("sh600887", "伊利股份"), ("sh600809", "山西汾酒"),
    # 电力
    ("sh600900", "长江电力"), ("sh600886", "国投电力"),
    # 家电
    ("sz000333", "美的集团"), ("sz000651", "格力电器"),
    # 煤炭
    ("sh601088", "中国神华"), ("sh600188", "兖矿能源"),
    # 运营商
    ("sh600941", "中国移动"),
    # 基建
    ("sh601390", "中国中铁"), ("sh601668", "中国建筑"),
    # 石化
    ("sh600028", "中国石化"),
    # 公用事业
    ("sh600025", "华能水电"),
    # 宽基ETF
    ("sh510050", "上证50ETF"), ("sh510300", "沪深300ETF"),
]

def get_quote(code):
    """获取腾讯行情"""
    url = f'https://qt.gtimg.cn/q={code}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode('gbk')
        vals = data.split('"')[1].split('~')
        return {
            'name': vals[1],
            'code': vals[2],
            'price': float(vals[3]),
            'prev_close': float(vals[4]),
            'open': float(vals[5]),
            'high': float(vals[33]),
            'low': float(vals[34]),
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

def get_kline(code, days=30):
    """获取日K线"""
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode('utf-8'))
        key = code.replace('sh', 'sh').replace('sz', 'sz')
        days_data = data.get('data', {}).get(key, {}).get('day', [])
        if not days_data:
            days_data = data.get('data', {}).get(key, {}).get('qfqday', [])
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

def scan_swing_opportunity(code, name):
    """扫描一只股票的短线波段机会"""
    quote = get_quote(code)
    if not quote:
        return None
    
    klines = get_kline(code, 30)
    if not klines or len(klines) < 10:
        return None
    
    closes = [k['close'] for k in klines]
    volumes = [k['volume'] for k in klines]
    highs = [k['high'] for k in klines]
    lows = [k['low'] for k in klines]
    
    price = quote['price']
    change_pct = quote['change_pct']
    amplitude = quote['amplitude']
    
    # 计算均线
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    
    if not all([ma5, ma10, ma20]):
        return None
    
    # 计算波动率（最近10日振幅均值）
    recent_amps = []
    for i in range(max(1, len(klines)-10), len(klines)):
        amp = (highs[i] - lows[i]) / closes[i-1] * 100
        recent_amps.append(amp)
    avg_amp = sum(recent_amps) / len(recent_amps) if recent_amps else 0
    
    # 计算成交量变化
    avg_vol_5 = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 0
    avg_vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 0
    vol_ratio = avg_vol_5 / avg_vol_20 if avg_vol_20 > 0 else 1
    
    # === 波段信号判断 ===
    signals = []
    
    # 信号1: 缩量回调至MA10/MA20支撑
    if price <= ma10 * 1.015 and price >= ma10 * 0.985:
        if vol_ratio < 0.8:  # 缩量
            signals.append(("缩量回踩MA10", f"价{price:.2f}≈MA10({ma10:.2f}), 量比{vol_ratio:.2f}"))
    
    if price <= ma20 * 1.015 and price >= ma20 * 0.985:
        if vol_ratio < 0.8:
            signals.append(("缩量回踩MA20", f"价{price:.2f}≈MA20({ma20:.2f}), 量比{vol_ratio:.2f}"))
    
    # 信号2: 连续下跌后缩量企稳（3连阴+缩量）
    if len(closes) >= 5:
        last_3 = closes[-3:]
        if all(last_3[i] < last_3[i-1] for i in range(1, 3)):
            if vol_ratio < 0.7 and change_pct >= -1.0:  # 今日跌幅收窄
                signals.append(("三连阴缩量企稳", f"3日跌{(last_3[0]-last_3[-1])/last_3[0]*100:.1f}%, 量比{vol_ratio:.2f}"))
    
    # 信号3: MACD金叉（简化版：短期均线上穿长期）
    if len(closes) >= 12:
        ma5_prev = calc_ma(closes[:-1], 5)
        ma10_prev = calc_ma(closes[:-1], 10)
        if ma5_prev and ma10_prev:
            if ma5_prev <= ma10_prev and ma5 > ma10:
                signals.append(("MA5上穿MA10", "金叉信号"))
    
    # 信号4: 今日回调幅度较大但缩量（可能是短线买点）
    if change_pct < -1.5 and vol_ratio < 0.8:
        signals.append(("回调缩量", f"跌{change_pct:.1f}%, 量比{vol_ratio:.2f}"))
    
    # 信号5: 今日放量突破MA5
    if price > ma5 and change_pct > 1.0 and vol_ratio > 1.2:
        signals.append(("放量站上MA5", f"涨{change_pct:.1f}%, 量比{vol_ratio:.2f}"))
    
    if not signals:
        return None
    
    return {
        'name': name,
        'code': code,
        'price': price,
        'change_pct': change_pct,
        'ma5': ma5,
        'ma10': ma10,
        'ma20': ma20,
        'avg_amp': avg_amp,
        'vol_ratio': vol_ratio,
        'signals': signals,
        'pe_ttm': quote['pe_ttm'],
        'pb': quote['pb'],
    }

# ========== 执行扫描 ==========
print("=" * 60)
print("稳定型股票短线波段扫描")
print(f"扫描时间: 2026-07-10 盘中")
print("=" * 60)

results = []
for code, name in STABLE_POOL:
    result = scan_swing_opportunity(code, name)
    if result:
        results.append(result)

if not results:
    print("\n当前无符合条件的短线波段机会")
    print("可能原因：")
    print("  1. 今日盘中波动较大，稳定型股票尚未出现明确信号")
    print("  2. 市场整体处于趋势行情中，短线回调机会较少")
    print("  3. 建议收盘后再扫描一次")
else:
    # 按信号强度排序
    results.sort(key=lambda x: len(x['signals']), reverse=True)
    
    for r in results:
        print(f"\n{'─' * 50}")
        print(f"{r['name']}({r['code']})  现价{r['price']:.2f} 涨跌{r['change_pct']:+.2f}%")
        print(f"  MA5={r['ma5']:.2f} MA10={r['ma10']:.2f} MA20={r['ma20']:.2f}")
        print(f"  量比={r['vol_ratio']:.2f} 平均振幅={r['avg_amp']:.1f}%")
        print(f"  信号:")
        for s in r['signals']:
            print(f"    {s[0]}: {s[1]}")
    
    print(f"\n{'=' * 60}")
    print(f"共扫描{len(STABLE_POOL)}只，发现{len(results)}只有机会")
    print("以上为量化筛选结果，仅供参考，不构成投资建议")
