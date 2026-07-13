"""
短线波段策略模块 - Swing Strategy
集成到量化模拟盘系统，基于稳定型股票池做1-2天短线波段交易

核心逻辑：
1. 每日收盘后扫描稳定型股票池
2. 识别短线机会（缩量回踩支撑、超卖反弹等）
3. 计算盈亏比（含手续费），生成交易信号
4. 将信号写入 strategy_shadow_signals 表
5. 模拟盘执行器(sim_executor)自动执行

手续费模型（与模拟盘一致）：
- 买入佣金: 成交额 * 0.025%（最低5元）
- 卖出佣金: 成交额 * 0.025%（最低5元）
- 印花税: 成交额 * 0.1%（仅卖出）
- 滑点: 0.02%（买卖各一次）
"""

import sqlite3
import urllib.request
import json
import datetime
import time
import os
import sys

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'sim_live_mirror.db')

# ========== 稳定型股票池 ==========
STABLE_POOL = [
    # 银行
    ("sh600036", "招商银行"), ("sh601166", "兴业银行"), ("sh600000", "浦发银行"),
    ("sh601398", "工商银行"), ("sh601288", "农业银行"), ("sh601939", "建设银行"),
    ("sh601328", "交通银行"), ("sh601988", "中国银行"),
    # 保险
    ("sh601318", "中国平安"), ("sh601628", "中国人寿"), ("sh601601", "中国太保"),
    # 消费
    ("sh600519", "贵州茅台"), ("sh600887", "伊利股份"), ("sh600809", "山西汾酒"),
    ("sz000568", "泸州老窖"), ("sh600600", "青岛啤酒"),
    # 家电
    ("sz000333", "美的集团"), ("sz000651", "格力电器"), ("sh600690", "海尔智家"),
    # 电力/公用事业
    ("sh600900", "长江电力"), ("sh600886", "国投电力"), ("sh600025", "华能水电"),
    ("sh601985", "中国核电"), ("sh600011", "华能国际"), ("sh600023", "浙能电力"),
    # 煤炭
    ("sh601088", "中国神华"), ("sh600188", "兖矿能源"), ("sh601225", "陕西煤业"),
    # 运营商
    ("sh600941", "中国移动"), ("sh600028", "中国石化"), ("sh601857", "中国石油"),
    # 基建
    ("sh601390", "中国中铁"), ("sh601668", "中国建筑"), ("sh601800", "中国交建"),
    # 交运
    ("sh601006", "大秦铁路"), ("sh600009", "上海机场"),
    # 医药
    ("sh600276", "恒瑞医药"), ("sz000538", "云南白药"),
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
        }
    except Exception as e:
        return None


def get_kline(code, days=30):
    """获取日K线（前复权）"""
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode('utf-8'))
        key = code.replace('sh', 'sh').replace('sz', 'sz')
        klines = data.get('data', {}).get(key, {}).get('day', [])
        if not klines:
            klines = data.get('data', {}).get(key, {}).get('qfqday', [])
        result = []
        for d in klines:
            result.append({
                'date': d[0],
                'open': float(d[1]),
                'close': float(d[2]),
                'high': float(d[3]),
                'low': float(d[4]),
                'volume': float(d[5]),
            })
        return result
    except Exception as e:
        return None


def calc_ma(prices, period):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def calc_rsi(prices, period=6):
    """计算RSI"""
    if len(prices) < period + 1:
        return 50
    gains, losses = 0, 0
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
    return 100 - 100 / (1 + rs)


def calc_cost(buy_price, sell_price, quantity):
    """计算交易成本（与模拟盘一致）"""
    buy_amount = buy_price * quantity
    sell_amount = sell_price * quantity
    
    commission_rate = 0.00025  # 万2.5
    min_commission = 5.0
    stamp_tax_rate = 0.001  # 印花税千1（卖出）
    slippage_rate = 0.0002  # 滑点万2
    
    buy_commission = max(buy_amount * commission_rate, min_commission)
    sell_commission = max(sell_amount * commission_rate, min_commission)
    stamp_tax = sell_amount * stamp_tax_rate
    slippage = (buy_amount + sell_amount) * slippage_rate
    
    total_cost = buy_commission + sell_commission + stamp_tax + slippage
    net_profit = (sell_price - buy_price) * quantity - total_cost
    
    return {
        'buy_commission': round(buy_commission, 2),
        'sell_commission': round(sell_commission, 2),
        'stamp_tax': round(stamp_tax, 2),
        'slippage': round(slippage, 2),
        'total_cost': round(total_cost, 2),
        'net_profit': round(net_profit, 2),
        'profit_pct': round(net_profit / (buy_amount + total_cost) * 100, 2),
    }


def scan_swing_signals(code, name):
    """
    扫描一只股票的短线波段信号
    返回信号列表，每个信号包含：信号类型、方向、目标价、止损价、预期收益、盈亏比
    """
    quote = get_quote(code)
    if not quote or quote['price'] == 0:
        return []
    
    klines = get_kline(code, 30)
    if not klines or len(klines) < 20:
        return []
    
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
    ma60 = calc_ma(closes, 60) if len(closes) >= 60 else None
    
    if not all([ma5, ma10, ma20]):
        return []
    
    # 计算RSI
    rsi6 = calc_rsi(closes, 6)
    rsi14 = calc_rsi(closes, 14)
    
    # 计算成交量变化
    avg_vol_5 = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 0
    avg_vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 0
    vol_ratio = avg_vol_5 / avg_vol_20 if avg_vol_20 > 0 else 1
    
    # 计算近5日平均振幅
    recent_amps = []
    for i in range(max(1, len(klines)-5), len(klines)):
        amp = (highs[i] - lows[i]) / closes[i-1] * 100
        recent_amps.append(amp)
    avg_amp = sum(recent_amps) / len(recent_amps) if recent_amps else 2.0
    
    signals = []
    
    # ====== 信号类型1: 缩量回踩MA10支撑 ======
    if price <= ma10 * 1.012 and price >= ma10 * 0.985:
        if vol_ratio < 0.85 and rsi6 < 50:
            # 目标价: MA20或前高
            target = round(ma20, 2)
            stop_loss = round(ma10 * 0.98, 2)
            expected_gain = (target - price) / price * 100
            expected_loss = (price - stop_loss) / price * 100
            
            if expected_gain > 0 and expected_loss > 0 and expected_gain / expected_loss >= 1.5:
                # 计算盈亏比（含手续费）
                cost_info = calc_cost(price, target, 100)
                cost_info_stop = calc_cost(price, stop_loss, 100)
                
                signals.append({
                    'type': '回踩MA10支撑',
                    'direction': 'BUY',
                    'entry_price': price,
                    'target_price': target,
                    'stop_loss': stop_loss,
                    'expected_gain_pct': round(expected_gain, 2),
                    'expected_loss_pct': round(expected_loss, 2),
                    'risk_reward_ratio': round(expected_gain / expected_loss, 2),
                    'net_profit_target': cost_info['net_profit'],
                    'net_loss_stop': cost_info_stop['net_profit'],
                    'total_cost': cost_info['total_cost'],
                    'confidence': '高' if expected_gain / expected_loss >= 2.5 else '中',
                    'reason': f"缩量回踩MA10({ma10:.2f})，RSI({rsi6:.0f})偏低，量比{vol_ratio:.2f}",
                })
    
    # ====== 信号类型2: 缩量回踩MA20支撑 ======
    if price <= ma20 * 1.012 and price >= ma20 * 0.985:
        if vol_ratio < 0.85 and rsi6 < 45:
            target = round(ma10, 2)
            stop_loss = round(ma20 * 0.98, 2)
            expected_gain = (target - price) / price * 100
            expected_loss = (price - stop_loss) / price * 100
            
            if expected_gain > 0 and expected_loss > 0 and expected_gain / expected_loss >= 1.5:
                cost_info = calc_cost(price, target, 100)
                cost_info_stop = calc_cost(price, stop_loss, 100)
                
                signals.append({
                    'type': '回踩MA20支撑',
                    'direction': 'BUY',
                    'entry_price': price,
                    'target_price': target,
                    'stop_loss': stop_loss,
                    'expected_gain_pct': round(expected_gain, 2),
                    'expected_loss_pct': round(expected_loss, 2),
                    'risk_reward_ratio': round(expected_gain / expected_loss, 2),
                    'net_profit_target': cost_info['net_profit'],
                    'net_loss_stop': cost_info_stop['net_profit'],
                    'total_cost': cost_info['total_cost'],
                    'confidence': '高' if expected_gain / expected_loss >= 2.5 else '中',
                    'reason': f"缩量回踩MA20({ma20:.2f})，RSI({rsi6:.0f})偏低，量比{vol_ratio:.2f}",
                })
    
    # ====== 信号类型3: RSI超卖反弹 ======
    if rsi6 < 30 and change_pct >= -3.0:
        target = round(ma10, 2)
        stop_loss = round(price * 0.97, 2)
        expected_gain = (target - price) / price * 100
        expected_loss = 3.0
        
        if target > price and expected_gain / expected_loss >= 1.5:
            cost_info = calc_cost(price, target, 100)
            signals.append({
                'type': 'RSI超卖反弹',
                'direction': 'BUY',
                'entry_price': price,
                'target_price': target,
                'stop_loss': stop_loss,
                'expected_gain_pct': round(expected_gain, 2),
                'expected_loss_pct': expected_loss,
                'risk_reward_ratio': round(expected_gain / expected_loss, 2),
                'net_profit_target': cost_info['net_profit'],
                'net_loss_stop': round((stop_loss - price) * 100 - cost_info['total_cost'], 2),
                'total_cost': cost_info['total_cost'],
                'confidence': '高' if rsi6 < 25 else '中',
                'reason': f"RSI超卖({rsi6:.0f})，短期超跌反弹机会",
            })
    
    # ====== 信号类型4: 连续缩量回调3天 ======
    if len(closes) >= 5:
        last_3_returns = [(closes[-i] - closes[-i-1]) / closes[-i-1] * 100 for i in range(1, 4)]
        if all(r < 0 for r in last_3_returns):
            total_drop = sum(last_3_returns)
            if total_drop < -2 and vol_ratio < 0.8:
                target = round(ma5, 2)
                stop_loss = round(price * 0.97, 2)
                expected_gain = (target - price) / price * 100
                expected_loss = 3.0
                
                if target > price and expected_gain / expected_loss >= 1.5:
                    cost_info = calc_cost(price, target, 100)
                    signals.append({
                        'type': '连续缩量回调',
                        'direction': 'BUY',
                        'entry_price': price,
                        'target_price': target,
                        'stop_loss': stop_loss,
                        'expected_gain_pct': round(expected_gain, 2),
                        'expected_loss_pct': expected_loss,
                        'risk_reward_ratio': round(expected_gain / expected_loss, 2),
                        'net_profit_target': cost_info['net_profit'],
                        'net_loss_stop': round((stop_loss - price) * 100 - cost_info['total_cost'], 2),
                        'total_cost': cost_info['total_cost'],
                        'confidence': '中',
                        'reason': f"连续3日回调({total_drop:.1f}%)，缩量企稳，量比{vol_ratio:.2f}",
                    })
    
    return signals


def save_signals_to_db(signals, scan_date):
    """将信号写入strategy_shadow_signals表"""
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    
    inserted = 0
    for sig in signals:
        # 检查是否已有相同信号
        c.execute("""
            SELECT id FROM strategy_shadow_signals 
            WHERE shadow_date = ? AND stock_code = ? AND signal_rule = ? AND signal_action = ?
        """, (scan_date, sig['code'], sig['signal_type'], 'BUY'))
        
        if c.fetchone():
            continue  # 已存在，跳过
        
        c.execute("""
            INSERT INTO strategy_shadow_signals 
            (shadow_date, shadow_time, strategy_id, stock_code, stock_name, price, position, 
             signal_action, signal_rule, signal_reason, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            scan_date,
            datetime.datetime.now().strftime('%H:%M:%S'),
            'swing',
            sig['code'],
            sig['name'],
            sig['entry_price'],
            0,  # position由执行器决定
            'BUY',
            sig['signal_type'],
            sig['reason'],
            sig['confidence'],
        ))
        inserted += 1
    
    db.commit()
    db.close()
    return inserted


def main():
    today = datetime.date.today().strftime('%Y-%m-%d')
    print(f'{"="*60}')
    print(f'  📊 短线波段策略扫描 - {today}')
    print(f'  {"="*60}')
    
    all_signals = []
    
    for code, name in STABLE_POOL:
        time.sleep(0.3)
        try:
            sigs = scan_swing_signals(code, name)
            for s in sigs:
                s['code'] = code
                s['name'] = name
                all_signals.append(s)
        except Exception as e:
            pass
    
    # 按盈亏比排序
    all_signals.sort(key=lambda x: x['risk_reward_ratio'], reverse=True)
    
    print(f'\n扫描股票池: {len(STABLE_POOL)}只')
    print(f'发现信号: {len(all_signals)}个\n')
    
    if not all_signals:
        print('❌ 当前无符合条件的短线波段信号')
        print('可能原因：市场整体趋势偏强/偏弱，缺乏短线回调机会')
        return
    
    print(f'{"="*60}')
    print(f'  📋 波段信号详情（按盈亏比排序）')
    print(f'  {"="*60}')
    
    for i, s in enumerate(all_signals):
        print(f'\n  {i+1}. {s["name"]}({s["code"]})')
        print(f'     信号: {s["type"]}')
        print(f'     方向: {s["direction"]} | 现价: {s["entry_price"]:.2f}')
        print(f'     目标: {s["target_price"]:.2f} (+{s["expected_gain_pct"]:.1f}%)')
        print(f'     止损: {s["stop_loss"]:.2f} (-{s["expected_loss_pct"]:.1f}%)')
        print(f'     盈亏比: {s["risk_reward_ratio"]:.2f} | 信心: {s["confidence"]}')
        print(f'     手续费: {s["total_cost"]:.2f}元')
        print(f'     预期净利(目标): {s["net_profit_target"]:.2f}元/100股')
        print(f'     预期净亏(止损): {s["net_loss_stop"]:.2f}元/100股')
        print(f'     原因: {s["reason"]}')
    
    # 保存到数据库
    inserted = save_signals_to_db(all_signals, today)
    print(f'\n{"="*60}')
    print(f'  ✅ 已写入 {inserted} 个信号到 strategy_shadow_signals 表')
    print(f'  ⚠️ 信号将由模拟盘执行器在下一个交易日开盘时处理')
    print(f'  {"="*60}')
    
    # 输出汇总建议
    print(f'\n📌 操作建议:')
    high_conf = [s for s in all_signals if s['confidence'] == '高']
    mid_conf = [s for s in all_signals if s['confidence'] == '中']
    
    if high_conf:
        print(f'  🟢 高置信度信号（建议关注）:')
        for s in high_conf:
            print(f'     - {s["name"]}({s["code"]}) 盈亏比{s["risk_reward_ratio"]:.2f}')
    if mid_conf:
        print(f'  🟡 中等置信度信号（可观察）:')
        for s in mid_conf[:3]:
            print(f'     - {s["name"]}({s["code"]}) 盈亏比{s["risk_reward_ratio"]:.2f}')


if __name__ == '__main__':
    main()
