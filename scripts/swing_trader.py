"""
swing_trader.py — 短线波段交易策略模块
集成到量化模拟盘系统，包含：
1. 稳定型股票池扫描
2. 技术指标分析（支撑位/阻力位/盈亏比）
3. 手续费计算（佣金万2.5+印花税万5）
4. 信号生成与下单
5. 每日收盘后自动执行
"""

import os
import sys
import json
import sqlite3
import urllib.request
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / 'data' / 'sim_live_mirror.db'

# 费率
COMMISSION_RATE = 0.00025   # 佣金万2.5
STAMP_TAX_RATE = 0.0005     # 印花税万5（仅卖出）
MIN_COMMISSION = 5.0        # 最低佣金5元

# 波段策略参数
SWING_CONFIG = {
    "account_id": 1,
    "max_positions": 3,
    "position_size_pct": 0.08,
    "max_position_size_pct": 0.15,
    "min_profit_pct": 0.005,
    "max_loss_pct": 0.01,
    "min_risk_reward_ratio": 1.5,
    "min_amplitude_pct": 2.0,
}

# 稳定型股票池
STABLE_POOL = [
    ("sh600036", "招商银行"), ("sh601166", "兴业银行"), ("sh600000", "浦发银行"),
    ("sh601318", "中国平安"), ("sh601628", "中国人寿"),
    ("sh600519", "贵州茅台"), ("sh600887", "伊利股份"), ("sh600809", "山西汾酒"),
    ("sh600900", "长江电力"), ("sh600886", "国投电力"),
    ("sz000333", "美的集团"), ("sz000651", "格力电器"),
    ("sh601088", "中国神华"), ("sh600188", "兖矿能源"),
    ("sh600941", "中国移动"),
    ("sh601390", "中国中铁"), ("sh601668", "中国建筑"),
    ("sh600028", "中国石化"),
    ("sh600025", "华能水电"),
    ("sh510050", "上证50ETF"), ("sh510300", "沪深300ETF"),
    ("sh601985", "中国核电"), ("sh600011", "华能国际"),
    ("sz000858", "五粮液"), ("sz000568", "泸州老窖"),
    ("sh600276", "恒瑞医药"), ("sz000538", "云南白药"),
    ("sh600585", "海螺水泥"), ("sh600019", "宝钢股份"),
    ("sh601857", "中国石油"),
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
        }
    except Exception as e:
        return None


def get_kline(code, days=30):
    """获取日K线数据"""
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


def calc_rsi(prices, period=6):
    if len(prices) < period + 1:
        return 50
    gains = 0
    losses = 0
    for i in range(-period, 0):
        diff = prices[i] - prices[i-1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_commission(amount):
    """计算买入佣金"""
    comm = amount * COMMISSION_RATE
    return max(comm, MIN_COMMISSION)


def calc_tax(amount):
    """计算卖出印花税"""
    return amount * STAMP_TAX_RATE


def calc_total_cost(buy_price, quantity):
    """计算买入总成本（含佣金）"""
    amount = buy_price * quantity
    comm = calc_commission(amount)
    return amount + comm, comm


def calc_sell_proceeds(sell_price, quantity):
    """计算卖出总收入（扣除佣金+印花税）"""
    amount = sell_price * quantity
    comm = calc_commission(amount)
    tax = calc_tax(amount)
    return amount - comm - tax, comm, tax


def scan_swing_opportunities():
    """扫描所有稳定型股票，返回波段机会列表"""
    results = []
    
    for code, name in STABLE_POOL:
        quote = get_quote(code)
        if not quote:
            continue
        
        klines = get_kline(code, 30)
        if not klines or len(klines) < 20:
            continue
        
        closes = [k['close'] for k in klines]
        volumes = [k['volume'] for k in klines]
        highs = [k['high'] for k in klines]
        lows = [k['low'] for k in klines]
        
        price = quote['price']
        change_pct = quote['change_pct']
        
        # 计算均线
        ma5 = calc_ma(closes, 5)
        ma10 = calc_ma(closes, 10)
        ma20 = calc_ma(closes, 20)
        
        if not all([ma5, ma10, ma20]):
            continue
        
        # RSI
        rsi = calc_rsi(closes, 6)
        
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
        
        signals = []
        score = 0
        
        # === 信号判断 ===
        
        # 条件A: 缩量回踩MA20支撑
        if price <= ma20 * 1.015 and price >= ma20 * 0.985:
            if vol_ratio < 0.8:
                signals.append(f"缩量回踩MA20({ma20:.2f})")
                score += 3
                if rsi < 40:
                    signals.append(f"RSI偏低({rsi:.0f})")
                    score += 1
        
        # 条件B: 缩量回踩MA10支撑
        if price <= ma10 * 1.01 and price >= ma10 * 0.99:
            if vol_ratio < 0.8:
                signals.append(f"缩量回踩MA10({ma10:.2f})")
                score += 2
        
        # 条件C: 连续3日缩量回调
        if len(closes) >= 5:
            last_3 = closes[-3:]
            if all(last_3[i] < last_3[i-1] for i in range(1, 3)):
                if vol_ratio < 0.7 and change_pct >= -1.0:
                    signals.append("三连阴缩量企稳")
                    score += 3
        
        # 条件D: RSI超卖
        if rsi < 30:
            signals.append(f"RSI超卖({rsi:.0f})")
            score += 3
        
        # 条件E: 布林下轨附近
        boll_mid = ma20
        boll_std = sum((c - boll_mid) ** 2 for c in closes[-20:]) / 20
        boll_std = boll_std ** 0.5
        boll_lower = boll_mid - 2 * boll_std
        if price <= boll_lower * 1.01:
            signals.append(f"布林下轨({boll_lower:.2f})附近")
            score += 2
        
        # 排除：涨跌停、振幅太小
        if abs(change_pct) > 9.5:
            continue
        if avg_amp < 1.5:
            continue
        
        if score >= 3:
            # 计算盈亏比
            support = min(ma20, ma10) if ma20 and ma10 else (ma20 or ma10)
            resistance = max(ma5, ma10) if ma5 and ma10 else (ma5 or ma10)
            
            if support and resistance and support > 0:
                potential_profit = (resistance - price) / price
                potential_loss = (price - support) / price
                
                if potential_loss > 0:
                    risk_reward = potential_profit / potential_loss
                else:
                    risk_reward = 0
            else:
                potential_profit = 0.01
                potential_loss = 0.01
                risk_reward = 1.0
            
            # 计算手续费
            buy_qty = max(100, int(10000 / price / 100) * 100)  # 约1万元
            total_cost, buy_comm = calc_total_cost(price, buy_qty)
            sell_proceeds, sell_comm, sell_tax = calc_sell_proceeds(price * 1.02, buy_qty)
            round_trip_fee = buy_comm + sell_comm + sell_tax
            fee_pct = round_trip_fee / total_cost * 100 if total_cost > 0 else 0
            
            results.append({
                'name': name,
                'code': code,
                'price': price,
                'change_pct': change_pct,
                'ma5': round(ma5, 2),
                'ma10': round(ma10, 2),
                'ma20': round(ma20, 2),
                'rsi': round(rsi, 1),
                'vol_ratio': round(vol_ratio, 2),
                'avg_amp': round(avg_amp, 1),
                'signals': signals,
                'score': score,
                'support': round(support, 2),
                'resistance': round(resistance, 2),
                'potential_profit_pct': round(potential_profit * 100, 2),
                'potential_loss_pct': round(potential_loss * 100, 2),
                'risk_reward_ratio': round(risk_reward, 2),
                'fee_pct': round(fee_pct, 3),
                'pe_ttm': quote['pe_ttm'],
                'pb': quote['pb'],
            })
    
    results.sort(key=lambda x: x['score'], reverse=True)
    return results


def save_to_db(results, scan_date):
    """保存扫描结果到数据库"""
    db = sqlite3.connect(str(DB_PATH))
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
            ma10 REAL,
            rsi REAL,
            vol_ratio REAL,
            support REAL,
            resistance REAL,
            potential_profit_pct REAL,
            potential_loss_pct REAL,
            risk_reward_ratio REAL,
            fee_pct REAL,
            pe_ttm REAL,
            pb REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    for r in results:
        c.execute("""
            INSERT INTO swing_scan_results 
            (scan_date, stock_code, stock_name, price, change_pct, score, signals, 
             ma20, ma10, rsi, vol_ratio, support, resistance,
             potential_profit_pct, potential_loss_pct, risk_reward_ratio, fee_pct, pe_ttm, pb)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            scan_date, r['code'], r['name'], r['price'], r['change_pct'],
            r['score'], "; ".join(r['signals']),
            r['ma20'], r['ma10'], r['rsi'], r['vol_ratio'],
            r['support'], r['resistance'],
            r['potential_profit_pct'], r['potential_loss_pct'], r['risk_reward_ratio'],
            r['fee_pct'], r['pe_ttm'], r['pb']
        ))
    
    db.commit()
    db.close()


def generate_report(results):
    """生成可读报告"""
    lines = []
    lines.append("=" * 60)
    lines.append(f"📊 短线波段扫描报告")
    lines.append(f"扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"扫描范围: 稳定型蓝筹股池 ({len(STABLE_POOL)}只)")
    lines.append("=" * 60)
    
    if not results:
        lines.append("\n❌ 当前无符合条件的短线波段机会")
        lines.append("建议：")
        lines.append("  1. 市场整体趋势偏强/偏弱时，稳定型股票回调机会较少")
        lines.append("  2. 可考虑扩大股票池范围")
        lines.append("  3. 收盘后再扫描一次确认")
        return "\n".join(lines)
    
    lines.append(f"\n✅ 发现 {len(results)} 只短线波段机会")
    lines.append("")
    
    # 按评分分组
    high_confidence = [r for r in results if r['score'] >= 5]
    medium_confidence = [r for r in results if 3 <= r['score'] < 5]
    
    if high_confidence:
        lines.append("【🟢 高置信度机会】")
        for r in high_confidence:
            sig_str = " | ".join(r['signals'])
            lines.append(f"  {r['name']}({r['code']}) 现价{r['price']:.2f} ({r['change_pct']:+.2f}%)")
            lines.append(f"    支撑={r['support']:.2f} 阻力={r['resistance']:.2f}")
            lines.append(f"    预期盈利={r['potential_profit_pct']:+.2f}% 预期亏损={r['potential_loss_pct']:.2f}%")
            lines.append(f"    盈亏比={r['risk_reward_ratio']:.2f} 手续费={r['fee_pct']:.3f}%")
            lines.append(f"    RSI={r['rsi']:.0f} 量比={r['vol_ratio']:.2f} 振幅={r['avg_amp']:.1f}%")
            lines.append(f"    信号: {sig_str}")
            lines.append("")
    
    if medium_confidence:
        lines.append("【🟡 中等置信度机会】")
        for r in medium_confidence:
            sig_str = " | ".join(r['signals'])
            lines.append(f"  {r['name']}({r['code']}) 现价{r['price']:.2f} ({r['change_pct']:+.2f}%)")
            lines.append(f"    支撑={r['support']:.2f} 阻力={r['resistance']:.2f}")
            lines.append(f"    盈亏比={r['risk_reward_ratio']:.2f} 手续费={r['fee_pct']:.3f}%")
            lines.append(f"    信号: {sig_str}")
            lines.append("")
    
    lines.append("【操作建议】")
    lines.append(f"  建议仓位：单只不超过总资金8%，同时持仓不超过{SWING_CONFIG['max_positions']}只")
    lines.append(f"  止损原则：跌破支撑位-2%或亏损超{SWING_CONFIG['max_loss_pct']*100:.0f}%止损")
    lines.append(f"  止盈原则：到达阻力位或盈利{SWING_CONFIG['min_profit_pct']*100*2:.0f}%以上分批止盈")
    lines.append(f"  持有周期：1-2天")
    lines.append("")
    lines.append("⚠️ 以上为量化筛选结果，仅供参考，不构成投资建议")
    
    return "\n".join(lines)


def main():
    scan_date = datetime.now().strftime("%Y-%m-%d")
    
    print(f"📡 开始扫描稳定型股票池...")
    results = scan_swing_opportunities()
    
    print(f"✅ 扫描完成，发现 {len(results)} 只波段机会")
    
    # 保存到数据库
    save_to_db(results, scan_date)
    print(f"💾 结果已保存到数据库")
    
    # 生成报告
    report = generate_report(results)
    print(report)
    
    return results


if __name__ == "__main__":
    main()
