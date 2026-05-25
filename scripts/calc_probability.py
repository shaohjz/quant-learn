"""
scripts/calc_probability.py — 止盈/止损概率估算器

基于历史 K 线数据估算：
  P(止盈) = 过去 N 个交易日中，从某个价位买入后在 T 天内上涨 ≥ X% 的历史概率
  P(止损) = 过去 N 个交易日中，从某个价位买入后在 T 天内下跌 ≥ Y% 的历史概率

方法：
  用过去 120 天的收盘价序列，模拟从每个点买入后持有 10 天（T+1 次日算起），
  统计最大涨幅 >= 止盈幅度的比例 = P(止盈)
  统计最大跌幅 >= 止损幅度的比例 = P(止损)
  
  期望收益 = P(止盈) × 止盈幅度 - P(止损) × 止损幅度
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np


def estimate_probabilities(close_prices: list[float], 
                           tp_pct: float = 0.15, 
                           sl_pct: float = 0.08,
                           hold_days: int = 10) -> dict:
    """
    估算止盈止损概率
    
    Args:
        close_prices: 收盘价序列（至少 60 个）
        tp_pct: 止盈幅度（0.15 = +15%）
        sl_pct: 止损幅度（0.08 = -8%，正数）
        hold_days: 持有天数（模拟在 T 天内触及止盈/止损的概率）
    
    Returns:
        {
            'p_tp': float,       # 止盈概率
            'p_sl': float,       # 止损概率
            'expected_pct': float,   # 期望收益%
            'kelly_pct': float,  # Kelly 建议仓位比例
            'sample_count': int, # 样本数
            'avg_max_up': float, # 平均最大涨幅
            'avg_max_down': float,  # 平均最大跌幅
        }
    """
    prices = np.array(close_prices, dtype=float)
    n = len(prices)
    
    if n < hold_days + 10:
        return None  # 数据不足
    
    tp_hits = 0
    sl_hits = 0
    samples = 0
    max_ups = []
    max_downs = []
    
    # 从每个交易日模拟买入
    for i in range(n - hold_days):
        entry = prices[i]
        if entry <= 0:
            continue
        
        # 未来 hold_days 天的价格
        future = prices[i+1:i+1+hold_days]
        
        # 相对于入场价的涨跌幅
        returns = (future - entry) / entry
        
        max_up = returns.max()
        max_down = returns.min()
        
        max_ups.append(max_up)
        max_downs.append(max_down)
        
        if max_up >= tp_pct:
            tp_hits += 1
        if max_down <= -sl_pct:
            sl_hits += 1
        
        samples += 1
    
    if samples == 0:
        return None
    
    p_tp = tp_hits / samples
    p_sl = sl_hits / samples
    
    # 期望收益 = P(止盈) × 止盈幅度 - P(止损) × 止损幅度
    # 简化：假设不触及任何线则持有到期，收益 ≈ 0
    expected_pct = p_tp * tp_pct * 100 - p_sl * sl_pct * 100
    
    # Kelly 公式: f = (p*b - q) / b
    # p = 胜率(P_tp), b = 盈亏比(tp/sl), q = 1-p
    b = tp_pct / sl_pct  # 盈亏比
    kelly_pct = max(0, (p_tp * b - (1 - p_tp)) / b)
    kelly_pct = min(kelly_pct, 0.25)  # 最多 25%
    
    return {
        'p_tp': round(p_tp, 3),
        'p_sl': round(p_sl, 3),
        'expected_pct': round(expected_pct, 2),
        'kelly_pct': round(kelly_pct, 3),
        'sample_count': samples,
        'avg_max_up': round(float(np.mean(max_ups)) * 100, 2),
        'avg_max_down': round(float(np.mean(max_downs)) * 100, 2),
    }


def fetch_close_prices(code: str, days: int = 120) -> list[float]:
    """用 BaoStock 拉历史收盘价"""
    import baostock as bs
    from datetime import datetime, timedelta
    
    # BaoStock 代码格式
    if code.startswith(('60', '68', '11', '5')):
        bs_code = f"sh.{code}"
    else:
        bs_code = f"sz.{code}"
    
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
    
    bs.login()
    rs = bs.query_history_k_data_plus(
        bs_code, "close",
        start_date=start_date, end_date=end_date,
        frequency="d", adjustflag="2"  # 前复权
    )
    
    closes = []
    while rs.error_code == '0' and rs.next():
        row = rs.get_row_data()
        try:
            closes.append(float(row[0]))
        except (ValueError, IndexError):
            continue
    bs.logout()
    
    return closes[-days:] if len(closes) > days else closes


def calc_expected_trade(code: str, entry_price: float, 
                        tp_pct: float = 0.15, sl_pct: float = 0.08,
                        hold_days: int = 10) -> dict | None:
    """
    一站式计算：给定股票代码和买入价，返回概率+期望收益
    """
    closes = fetch_close_prices(code, days=120)
    if len(closes) < 30:
        return None
    
    result = estimate_probabilities(closes, tp_pct, sl_pct, hold_days)
    if result is None:
        return None
    
    # 加上价格信息
    result['code'] = code
    result['entry_price'] = entry_price
    result['tp_price'] = round(entry_price * (1 + tp_pct), 2)
    result['sl_price'] = round(entry_price * (1 - sl_pct), 2)
    result['tp_pct'] = tp_pct
    result['sl_pct'] = sl_pct
    
    return result


# ====================================================================
#  测试
# ====================================================================
if __name__ == '__main__':
    # 测试几只当前持仓/观察股
    test_stocks = [
        ('601728', 6.05, '中国电信'),
        ('603757', 61.66, '大元泵业'),
        ('002290', 99.13, '禾盛新材'),
    ]
    
    for code, price, name in test_stocks:
        print(f"\n=== {name} {code} 买入@{price} ===")
        result = calc_expected_trade(code, price, tp_pct=0.15, sl_pct=0.08, hold_days=10)
        if result:
            print(f"  止盈概率 P(+15%): {result['p_tp']*100:.1f}%")
            print(f"  止损概率 P(-8%):  {result['p_sl']*100:.1f}%")
            print(f"  期望收益: {result['expected_pct']:+.2f}%")
            print(f"  Kelly 仓位: {result['kelly_pct']*100:.1f}%")
            print(f"  样本数: {result['sample_count']}")
            print(f"  历史平均最大涨幅: +{result['avg_max_up']:.2f}%")
            print(f"  历史平均最大跌幅: {result['avg_max_down']:.2f}%")
        else:
            print("  数据不足")
