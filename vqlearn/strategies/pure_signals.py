"""
vqlearn/strategies/pure_signals.py

纯策略层：只接受 bars + position + rules，返回 Signal。
没有任何 IO（不发通知、不写库、不查交易时段）。
回测和实盘都调用这一层。

设计原则：
- 输入：历史 N 日 OHLCV bars（DataFrame）+ 当前持仓 + 规则参数
- 输出：Signal 对象（action: BUY_LIGHT / BUY_HEAVY / SELL_HALF / SELL_ALL / NO_ACTION）
- 不依赖 vnpy / 不查数据库 / 不发通知
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


# ============== 信号类型 ==============
@dataclass
class Signal:
    """策略产出的交易信号（纯数据，无 IO）"""
    action: str          # 'BUY_LIGHT' | 'BUY_HEAVY' | 'SELL_HALF' | 'SELL_ALL' | 'NO_ACTION'
    rule_name: str       # 'buy_zone' | 'buy_strong' | 'trend_break' | 'take_profit' | ''
    reason: str          # 人类可读的解释
    confidence: float = 1.0  # 0-1，置信度（多策略投票时用）
    metadata: dict = field(default_factory=dict)


# ============== 策略抽象基类 ==============
class StrategyBase:
    """所有策略的基类"""
    strategy_id: str = "base"
    version: str = "v1"
    description: str = ""

    def decide(self, bars: pd.DataFrame, position: int, rules: dict) -> Signal:
        """
        参数：
          bars: 历史 K 线（含今天最新一条），columns=[date,open,high,low,close,volume]
          position: 当前持仓数量（股数，0=无仓）
          rules: 阈值参数 {'buy_zone': 15.78, 'buy_strong': 14.22, ...}
        返回：
          Signal 对象
        """
        return Signal(action='NO_ACTION', rule_name='', reason='base 不下单')


# ============== 策略 1: ThresholdAlert ==============
class ThresholdAlertStrategy(StrategyBase):
    """阈值触发策略（vqlearn live 当前在用）

    规则：
    - buy_zone: 价格 ≤ buy_zone → BUY_LIGHT（试探买）
    - buy_strong: 价格 ≤ buy_strong → BUY_HEAVY（加仓）
    - trend_break: 价格 ≤ trend_break 且持仓 > 0 → SELL_HALF
    - take_profit: 价格 ≥ take_profit 且持仓 > 0 → SELL_HALF
    """
    strategy_id = "threshold_alert"
    version = "v1"
    description = "阈值触发：超跌买入、破位止损、达到目标止盈"

    def decide(self, bars: pd.DataFrame, position: int, rules: dict) -> Signal:
        if bars is None or len(bars) == 0:
            return Signal(action='NO_ACTION', rule_name='', reason='无数据')

        price = float(bars.iloc[-1]['close'])
        bz = float(rules.get('buy_zone') or 0)
        bs = float(rules.get('buy_strong') or 0)
        tb = float(rules.get('trend_break') or 0)
        tp = float(rules.get('take_profit') or 0)

        # 卖出（持仓 > 0）
        if position > 0:
            if tp > 0 and price >= tp:
                return Signal(action='SELL_HALF', rule_name='take_profit',
                              reason=f'price {price:.2f} ≥ take_profit {tp:.2f}')
            if tb > 0 and price <= tb:
                return Signal(action='SELL_HALF', rule_name='trend_break',
                              reason=f'price {price:.2f} ≤ trend_break {tb:.2f}')

        # 买入（持仓 == 0 或加仓）
        if bs > 0 and price <= bs:
            return Signal(action='BUY_HEAVY', rule_name='buy_strong',
                          reason=f'price {price:.2f} ≤ buy_strong {bs:.2f}')
        if bz > 0 and price <= bz:
            return Signal(action='BUY_LIGHT', rule_name='buy_zone',
                          reason=f'price {price:.2f} ≤ buy_zone {bz:.2f}')

        return Signal(action='NO_ACTION', rule_name='', reason='无信号')


# ============== 策略 2: MACD ==============
class MACDStrategy(StrategyBase):
    """MACD 金叉死叉策略"""
    strategy_id = "macd"
    version = "v1"
    description = "MACD 金叉买、死叉卖"

    def decide(self, bars: pd.DataFrame, position: int, rules: dict) -> Signal:
        if bars is None or len(bars) < 35:
            return Signal(action='NO_ACTION', rule_name='', reason='数据不足')

        # MACD 计算
        ema12 = bars['close'].ewm(span=12, adjust=False).mean()
        ema26 = bars['close'].ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd = (dif - dea) * 2

        if len(macd) < 3:
            return Signal(action='NO_ACTION', rule_name='', reason='指标数据不足')

        cur_macd = float(macd.iloc[-1])
        prev_macd = float(macd.iloc[-2])

        # 金叉（macd 从负转正）
        if prev_macd <= 0 and cur_macd > 0:
            if position == 0:
                return Signal(action='BUY_LIGHT', rule_name='macd_golden',
                              reason=f'MACD 金叉 {prev_macd:.3f}→{cur_macd:.3f}')

        # 死叉（macd 从正转负）
        if prev_macd >= 0 and cur_macd < 0:
            if position > 0:
                return Signal(action='SELL_ALL', rule_name='macd_death',
                              reason=f'MACD 死叉 {prev_macd:.3f}→{cur_macd:.3f}')

        return Signal(action='NO_ACTION', rule_name='', reason='无信号')


# ============== 策略 3: SMA Cross（双均线）==============
class SMACrossStrategy(StrategyBase):
    """5/20 双均线交叉策略"""
    strategy_id = "sma_cross"
    version = "v1"
    description = "5 日均线上穿/下穿 20 日均线"

    def decide(self, bars: pd.DataFrame, position: int, rules: dict) -> Signal:
        if bars is None or len(bars) < 22:
            return Signal(action='NO_ACTION', rule_name='', reason='数据不足')

        sma5 = bars['close'].rolling(5).mean()
        sma20 = bars['close'].rolling(20).mean()

        cur5, prev5 = float(sma5.iloc[-1]), float(sma5.iloc[-2])
        cur20, prev20 = float(sma20.iloc[-1]), float(sma20.iloc[-2])

        # 金叉
        if prev5 <= prev20 and cur5 > cur20:
            if position == 0:
                return Signal(action='BUY_LIGHT', rule_name='sma_golden',
                              reason=f'SMA5 上穿 SMA20 ({cur5:.2f} > {cur20:.2f})')

        # 死叉
        if prev5 >= prev20 and cur5 < cur20:
            if position > 0:
                return Signal(action='SELL_ALL', rule_name='sma_death',
                              reason=f'SMA5 下穿 SMA20 ({cur5:.2f} < {cur20:.2f})')

        return Signal(action='NO_ACTION', rule_name='', reason='无信号')


# ============== 策略 4: Bollinger Bands ==============
class BollingerStrategy(StrategyBase):
    """布林带均值回归"""
    strategy_id = "bollinger"
    version = "v1"
    description = "下穿下轨买、上穿上轨卖"

    def decide(self, bars: pd.DataFrame, position: int, rules: dict) -> Signal:
        if bars is None or len(bars) < 22:
            return Signal(action='NO_ACTION', rule_name='', reason='数据不足')

        sma20 = bars['close'].rolling(20).mean()
        std20 = bars['close'].rolling(20).std()
        upper = sma20 + 2 * std20
        lower = sma20 - 2 * std20

        price = float(bars.iloc[-1]['close'])
        cur_upper = float(upper.iloc[-1])
        cur_lower = float(lower.iloc[-1])
        cur_mid = float(sma20.iloc[-1])

        # 跌破下轨 → 买
        if price <= cur_lower and position == 0:
            return Signal(action='BUY_LIGHT', rule_name='boll_lower',
                          reason=f'price {price:.2f} ≤ lower {cur_lower:.2f}')

        # 突破上轨 → 卖
        if price >= cur_upper and position > 0:
            return Signal(action='SELL_HALF', rule_name='boll_upper',
                          reason=f'price {price:.2f} ≥ upper {cur_upper:.2f}')

        return Signal(action='NO_ACTION', rule_name='', reason='无信号')


# ============== 策略 5: Composite（组合）==============
class CompositeStrategy(StrategyBase):
    """组合策略：MACD + SMA 双确认"""
    strategy_id = "composite"
    version = "v1"
    description = "MACD 金叉 + SMA 多头排列才买；任一死叉就卖"

    def decide(self, bars: pd.DataFrame, position: int, rules: dict) -> Signal:
        macd_strat = MACDStrategy()
        sma_strat = SMACrossStrategy()
        macd_sig = macd_strat.decide(bars, position, rules)
        sma_sig = sma_strat.decide(bars, position, rules)

        # 卖：任一死叉
        if position > 0:
            if 'death' in macd_sig.rule_name or 'death' in sma_sig.rule_name:
                return Signal(action='SELL_ALL', rule_name='composite_sell',
                              reason=f'死叉信号 (macd={macd_sig.rule_name}, sma={sma_sig.rule_name})')

        # 买：双金叉确认
        if position == 0:
            if 'golden' in macd_sig.rule_name and 'golden' in sma_sig.rule_name:
                return Signal(action='BUY_HEAVY', rule_name='composite_buy',
                              reason='MACD 金叉 + SMA 金叉')
            if 'golden' in macd_sig.rule_name or 'golden' in sma_sig.rule_name:
                return Signal(action='BUY_LIGHT', rule_name='composite_buy_partial',
                              reason=f'单金叉确认 (macd={macd_sig.rule_name}, sma={sma_sig.rule_name})')

        return Signal(action='NO_ACTION', rule_name='', reason='无信号')


# ============== 策略注册表 ==============
ALL_STRATEGIES = {
    'threshold_alert': ThresholdAlertStrategy,
    'macd': MACDStrategy,
    'sma_cross': SMACrossStrategy,
    'bollinger': BollingerStrategy,
    'composite': CompositeStrategy,
}


def get_strategy(strategy_id: str) -> StrategyBase:
    """工厂方法"""
    cls = ALL_STRATEGIES.get(strategy_id)
    if cls is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")
    return cls()
