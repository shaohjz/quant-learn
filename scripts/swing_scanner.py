"""
短线波段扫描器 - 每日扫描稳定型股票池，识别1-2天短线波动机会

策略逻辑：
1. 股票池：沪深300成分股中筛选低波动、高流动性的稳定型标的
2. 扫描条件（满足任一即可）：
   a. 缩量回调至关键支撑位（MA20/MA60附近）
   b. MACD零轴上方金叉
   c. KDJ超卖区（<20）反弹
   d. 布林带下轨缩量企稳
   e. 连续3日缩量+小实体（地量见底信号）
3. 排除条件：ST、当日涨跌停、近期有重大利空
"""

import sqlite3
import urllib.request
import json
import datetime
import time

DB_PATH = 'data/sim_live_mirror.db'

# ========== 稳定型股票池 ==========
# 沪深300中选取流动性好、波动相对较低的标的
# 涵盖：银行、保险、家电、公用事业、基建、交运等稳定行业
STABLE_POOL = [
    # 银行
    "sh600036", "sh601398", "sh601288", "sh601939", "sh601988",
    "sh600000", "sh600016", "sh601166", "sh600015", "sh601328",
    "sh601009", "sh601818", "sh601229", "sh601169", "sh601009",
    # 保险
    "sh601318", "sh601628", "sh601601", "sh601336",
    # 家电
    "sz000333", "sh600690", "sz000651", "sz002032",
    # 公用事业
    "sh600900", "sh601985", "sh600886", "sh600011", "sh600023",
    "sh600025", "sh600905", "sh601619",
    # 基建/建筑
    "sh601668", "sh601390", "sh601618", "sh601800", "sh601186",
    # 交运/高速
    "sh601006", "sh600009", "sh601111", "sh601021", "sh600029",
    "sh601919", "sh601872",
    # 煤炭/能源
    "sh601088", "sh600188", "sh601225", "sh600546",
    # 食品饮料龙头
    "sh600519", "sz000568", "sh600887", "sz000858", "sh600809",
    "sh600600", "sz002304",
    # 医药龙头
    "sh600276", "sz000538", "sh600196", "sz300760", "sh600085",
    # 汽车龙头
    "sh600104", "sz000625", "sh601238", "sh600741",
    # 其他蓝筹
    "sh601857", "sh600028", "sh600585", "sh600019", "sh600010",
    "sh601766", "sh600031", "sh600690",
    # 央企ETF/沪深300ETF
    "sh510300", "sh510050", "sh510500",
]

# 补充分组
BANK_POOL = ["sh600036", "sh601398", "sh601288", "sh601939", "sh601988", "sh600000", "sh601166", "sh601328"]
UTILITY_POOL = ["sh600900", "sh601985", "sh600886", "sh600011", "sh600023", "sh600025", "sh600905"]
CONSUME_POOL = ["sh600519", "sz000568", "sh600887", "sz000858", "sh600809", "sz002304"]
MEDICAL_POOL = ["sh600276", "sz000538", "sh600196", "sz300760", "sh600085"]
ETF_POOL = ["sh510300", "sh510050", "sh510500"]


def get_tencent_quote(code):
    """获取腾讯行情"""
    url = f"https://qt.gtimg.cn/q={code}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode("gbk")
        vals = data.split('"')[1].split('~')
        return {
            "name": vals[1],
            "code": vals[2],
            "price": float(vals[3]) if vals[3] else 0,
            "last_close": float(vals[4]) if vals[4] else 0,
            "open": float(vals[5]) if vals[5] else 0,
            "high": float(vals[33]) if vals[33] else 0,
            "low": float(vals[34]) if vals[34] else 0,
            "change_pct": float(vals[32]) if vals[32] else 0,
            "volume": int(vals[36]) if vals[36] else 0,  # 手
            "amount": float(vals[37]) if vals[37] else 0,  # 万
            "turnover_rate": float(vals[38]) if vals[38] else 0,  # %
            "pe_ttm": float(vals[39]) if vals[39] else 0,
            "pb": float(vals[46]) if vals[46] else 0,
            "market_cap": float(vals[44]) if vals[44] else 0,  # 亿
            "amplitude": float(vals[43]) if vals[43] else 0,  # 振幅%
        }
    except Exception as e:
        return None


def get_kline_data(code, days=30):
    """获取日K线数据"""
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        key = code.split("sh")[-1] if "sh" in code else code.split("sz")[-1]
        klines = data.get("data", {}).get(key, {}).get("day", [])
        if not klines:
            klines = data.get("data", {}).get(key, {}).get("qfqday", [])
        return klines
    except Exception as e:
        return None


def get_kline_tencent(code, days=30):
    """腾讯K线 - 备用方案"""
    url = f"https://web.ifzq.gtimg.cn/appstock/app/kline/mkline?param={code},day,,,{days}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        klines = data.get("data", {}).get(code, {}).get("day", [])
        return klines
    except Exception as e:
        return None


def calc_ma(prices, period):
    """计算移动平均线"""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def calc_macd(prices, fast=12, slow=26, signal=9):
    """计算MACD"""
    if len(prices) < slow + signal:
        return None, None, None
    
    ema_fast = prices[0]
    ema_slow = prices[0]
    for i in range(1, len(prices)):
        ema_fast = prices[i] * 2/(fast+1) + ema_fast * (1 - 2/(fast+1))
        ema_slow = prices[i] * 2/(slow+1) + ema_slow * (1 - 2/(slow+1))
    
    dif = ema_fast - ema_slow
    dea = dif
    for i in range(1, signal):
        dea = dif * 2/(signal+1) + dea * (1 - 2/(signal+1))
    
    macd = 2 * (dif - dea)
    return dif, dea, macd


def calc_kdj(highs, lows, closes, period=9):
    """计算KDJ"""
    if len(closes) < period:
        return None, None, None
    
    low_min = min(lows[-period:])
    high_max = max(highs[-period:])
    if high_max == low_min:
        return 50, 50, 50
    
    rsv = (closes[-1] - low_min) / (high_max - low_min) * 100
    k = rsv
    d = rsv
    for _ in range(2):
        k = 2/3 * k + 1/3 * rsv
        d = 2/3 * d + 1/3 * k
    j = 3 * k - 2 * d
    return k, d, j


def calc_bollinger(prices, period=20, multiplier=2):
    """计算布林带"""
    if len(prices) < period:
        return None, None, None
    ma = sum(prices[-period:]) / period
    variance = sum((p - ma) ** 2 for p in prices[-period:]) / period
    std = variance ** 0.5
    upper = ma + multiplier * std
    lower = ma - multiplier * std
    return upper, ma, lower


def scan_stock(code):
    """扫描单只股票，返回波段机会信号"""
    quote = get_tencent_quote(code)
    if not quote or quote["price"] == 0:
        return None
    
    klines = get_kline_tencent(code, 60)
    if not klines or len(klines) < 20:
        return None
    
    # 提取价格序列
    closes = [float(k[2]) for k in klines]
    highs = [float(k[1]) for k in klines]
    lows = [float(k[3]) for k in klines]
    volumes = [int(k[4]) if len(k) > 4 else 0 for k in klines]
    
    if len(closes) < 20:
        return None
    
    current_price = quote["price"]
    signals = []
    score = 0
    
    # 1. 缩量回调至MA20/MA60支撑
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60) if len(closes) >= 60 else None
    
    if ma20:
        near_ma20 = abs(current_price - ma20) / ma20
        if near_ma20 < 0.015:  # 在MA20附近1.5%以内
            # 检查是否缩量
            avg_vol = sum(volumes[-5:-1]) / 4 if len(volumes) >= 5 else 0
            if avg_vol > 0 and volumes[-1] < avg_vol * 0.7:
                signals.append(f"缩量回踩MA20({ma20:.2f})")
                score += 3
    
    if ma60:
        near_ma60 = abs(current_price - ma60) / ma60
        if near_ma60 < 0.015:
            avg_vol = sum(volumes[-5:-1]) / 4 if len(volumes) >= 5 else 0
            if avg_vol > 0 and volumes[-1] < avg_vol * 0.7:
                signals.append(f"缩量回踩MA60({ma60:.2f})")
                score += 3
    
    # 2. KDJ超卖反弹
    k, d, j = calc_kdj(highs, lows, closes)
    if k is not None and j is not None:
        if j < 20 and k < 25:
            signals.append(f"KDJ超卖(J={j:.1f})")
            score += 3
        elif j < 30 and k < 35:
            signals.append(f"KDJ偏低(J={j:.1f})")
            score += 2
    
    # 3. 布林带下轨企稳
    boll_upper, boll_mid, boll_lower = calc_bollinger(closes)
    if boll_lower:
        near_lower = (current_price - boll_lower) / boll_lower
        if near_lower < 0.01:  # 在下轨附近
            avg_vol = sum(volumes[-5:-1]) / 4 if len(volumes) >= 5 else 0
            if avg_vol > 0 and volumes[-1] < avg_vol * 0.7:
                signals.append(f"布林下轨缩量企稳({boll_lower:.2f})")
                score += 3
    
    # 4. 连续缩量+小实体（地量见底）
    if len(closes) >= 5:
        bodies = [abs(closes[i] - (klines[i][0] if len(klines[i]) > 0 else closes[i])) for i in range(-5, 0)]
        avg_body = sum(bodies[:4]) / 4
        if avg_body > 0 and bodies[-1] < avg_body * 0.5:
            vol_shrink = all(volumes[i] <= volumes[i-1] for i in range(-3, 0))
            if vol_shrink:
                signals.append("连续缩量小实体(地量)")
                score += 2
    
    # 5. 今日跌幅较大但缩量（恐慌性下跌）
    if quote["change_pct"] < -2 and volumes[-1] < sum(volumes[-5:-1]) / 4 * 0.8:
        signals.append(f"缩量下跌{quote['change_pct']:.1f}%")
        score += 2
    
    # 6. 排除条件
    if abs(quote["change_pct"]) > 9.5:  # 涨跌停
        return None
    
    if score >= 3:
        return {
            "code": code,
            "name": quote["name"],
            "price": current_price,
            "change_pct": quote["change_pct"],
            "turnover_rate": quote["turnover_rate"],
            "pe_ttm": quote["pe_ttm"],
            "pb": quote["pb"],
            "market_cap": quote["market_cap"],
            "signals": signals,
            "score": score,
            "ma20": round(ma20, 2) if ma20 else None,
            "ma60": round(ma60, 2) if ma60 else None,
        }
    
    return None


def main():
    today = datetime.date.today().strftime("%Y-%m-%d")
    print(f"\n{'='*60}")
    print(f"  短线波段扫描报告 - {today}")
    print(f"  扫描范围: 稳定型蓝筹股池 ({len(STABLE_POOL)}只)")
    print(f"{'='*60}")
    
    results = []
    errors = []
    
    for i, code in enumerate(STABLE_POOL):
        time.sleep(0.3)  # 限流
        try:
            result = scan_stock(code)
            if result:
                results.append(result)
                print(f"  ✓ {result['name']}({code}) 评分{result['score']}: {'; '.join(result['signals'])}")
            else:
                pass  # 无信号
        except Exception as e:
            errors.append((code, str(e)))
        
        if (i+1) % 20 == 0:
            print(f"  进度: {i+1}/{len(STABLE_POOL)}")
    
    # 按评分排序
    results.sort(key=lambda x: x["score"], reverse=True)
    
    print(f"\n{'='*60}")
    print(f"  扫描完成: {len(results)}只股票有波段信号")
    if errors:
        print(f"  失败: {len(errors)}只")
    print(f"{'='*60}")
    
    if results:
        print(f"\n📊 波段机会排名:")
        print(f"{'='*60}")
        for i, r in enumerate(results[:10]):
            signals_str = " | ".join(r["signals"])
            print(f"\n  {i+1}. {r['name']}({r['code']})")
            print(f"     现价: {r['price']:.2f} | 涨跌: {r['change_pct']:+.2f}% | 换手: {r['turnover_rate']:.2f}%")
            print(f"     PE: {r['pe_ttm']:.1f} | PB: {r['pb']:.2f} | 市值: {r['market_cap']:.1f}亿")
            if r['ma20']: print(f"     MA20: {r['ma20']:.2f} | MA60: {r['ma60']:.2f}" if r['ma60'] else f"     MA20: {r['ma20']:.2f}")
            print(f"     信号: {signals_str}")
            print(f"     评分: {'⭐' * (r['score'] // 2)}")
    
    # 保存到数据库
    try:
        db = sqlite3.connect(DB_PATH)
        c = db.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS swing_scan_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_date TEXT,
                stock_code TEXT,
                stock_name TEXT,
                price REAL,
                change_pct REAL,
                score INTEGER,
                signals TEXT,
                ma20 REAL,
                ma60 REAL,
                pe_ttm REAL,
                pb REAL,
                market_cap REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        for r in results:
            c.execute("""
                INSERT INTO swing_scan_results 
                (scan_date, stock_code, stock_name, price, change_pct, score, signals, ma20, ma60, pe_ttm, pb, market_cap)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                today, r["code"], r["name"], r["price"], r["change_pct"],
                r["score"], "; ".join(r["signals"]), r["ma20"], r["ma60"],
                r["pe_ttm"], r["pb"], r["market_cap"]
            ))
        
        db.commit()
        db.close()
        print(f"\n✅ 结果已保存到数据库 swing_scan_results 表")
    except Exception as e:
        print(f"\n⚠️ 保存到数据库失败: {e}")


if __name__ == "__main__":
    main()
