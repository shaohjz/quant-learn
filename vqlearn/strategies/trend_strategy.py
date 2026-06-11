"""
vqlearn/strategies/trend_strategy.py — 趋势跟随策略 (v1 2026-05-22)

设计思路（牛市行情用）：
  1. 入场：放量突破 N 日新高 + 均线多头排列（MA5>MA10>MA20）
  2. 加仓：突破后回踩 MA10 不破 → 加仓
  3. 跟踪止损：跌破 MA10 / ATR 倍数止损
  4. 出场：跌破 MA20 或 RSI 超买回落

集成方式：
  - 不替代 threshold_strategy，而是并行跑
  - 仅订阅 watchlist 里 source='趋势池' 的股票（用户在 config.yaml 标记）
  - 信号触发后调用 sim_executor 自动下单（限学习账户）

为避免一次梭哈：
  - 每只单次买入预算 = min(2000, cash * 0.1)
  - 趋势策略最多持仓 10 只
  - 无明确止盈，依赖跟踪止损
"""
from __future__ import annotations

import os
import sys
import logging
from datetime import datetime, time as dtime
from collections import deque
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault('QUANT_DB_PATH', str(ROOT / 'data' / 'sim_live_mirror.db'))

try:
    from vnpy_ctastrategy import CtaTemplate, StopOrder
    from vnpy.trader.object import TickData, BarData, OrderData, TradeData
    HAS_VNPY = True
except ImportError:
    HAS_VNPY = False
    CtaTemplate = object
    TickData = BarData = OrderData = TradeData = StopOrder = None

try:
    from scripts.sim_executor import execute_trade as _sim_execute_trade
    from scripts.sim_executor import set_active_account, active_account_id
except Exception:
    _sim_execute_trade = None
    set_active_account = None
    active_account_id = None


logger = logging.getLogger('trend-strat')


def _is_trading_hours() -> bool:
    n = datetime.now()
    if n.weekday() >= 5:
        return False
    t = n.time()
    return (dtime(9, 30) <= t <= dtime(11, 30)) or (dtime(13, 0) <= t <= dtime(15, 0))


# -----------------------------------------------------------
#  内存级技术指标计算器（轻量替代 ta-lib，避免依赖问题）
# -----------------------------------------------------------
class TrendIndicators:
    """轻量趋势指标：MA / ATR / RSI / 成交量比"""

    def __init__(self, ma_periods=(5, 10, 20, 60), atr_period=14, rsi_period=14):
        self.ma_periods = ma_periods
        self.atr_period = atr_period
        self.rsi_period = rsi_period
        self.max_window = max(max(ma_periods), atr_period, rsi_period) + 5
        self.closes = deque(maxlen=self.max_window)
        self.highs = deque(maxlen=self.max_window)
        self.lows = deque(maxlen=self.max_window)
        self.volumes = deque(maxlen=self.max_window)

    def update(self, close: float, high: float, low: float, volume: float):
        self.closes.append(close)
        self.highs.append(high)
        self.lows.append(low)
        self.volumes.append(volume)

    def ma(self, period: int) -> Optional[float]:
        if len(self.closes) < period:
            return None
        return sum(list(self.closes)[-period:]) / period

    def n_day_high(self, period: int) -> Optional[float]:
        if len(self.highs) < period:
            return None
        return max(list(self.highs)[-period:])

    def atr(self) -> Optional[float]:
        if len(self.closes) < self.atr_period + 1:
            return None
        trs = []
        closes = list(self.closes)
        highs = list(self.highs)
        lows = list(self.lows)
        for i in range(-self.atr_period, 0):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])
            )
            trs.append(tr)
        return sum(trs) / len(trs)

    def rsi(self) -> Optional[float]:
        if len(self.closes) < self.rsi_period + 1:
            return None
        gains = []
        losses = []
        closes = list(self.closes)
        for i in range(-self.rsi_period, 0):
            diff = closes[i] - closes[i - 1]
            if diff > 0:
                gains.append(diff)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(-diff)
        avg_gain = sum(gains) / len(gains)
        avg_loss = sum(losses) / len(losses)
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def vol_avg(self, period: int = 5) -> Optional[float]:
        if len(self.volumes) < period:
            return None
        return sum(list(self.volumes)[-period:]) / period


# -----------------------------------------------------------
#  趋势策略主体（vnpy CtaTemplate 子类）
# -----------------------------------------------------------
class TrendFollowStrategy(CtaTemplate if HAS_VNPY else object):
    """趋势跟随策略
    
    参数:
      breakout_period: 突破周期（默认 20 日）
      vol_ratio: 突破日成交量需 ≥ X 倍均量
      ma_fast/slow: 均线
      atr_stop_x: ATR 倍数止损
      rsi_overbought: RSI 超买阈值
    """
    author = "openclaw"
    
    # 参数（vnpy 框架要求）
    breakout_period: int = 20
    vol_ratio: float = 1.5
    ma_fast: int = 10
    ma_slow: int = 20
    atr_stop_x: float = 2.0
    rsi_overbought: float = 75.0
    
    # 状态变量
    pos: int = 0
    entry_price: float = 0.0
    highest_since_entry: float = 0.0
    
    parameters = ["breakout_period", "vol_ratio", "ma_fast", "ma_slow", "atr_stop_x", "rsi_overbought"]
    variables = ["pos", "entry_price", "highest_since_entry"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        if HAS_VNPY:
            super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.indicators = TrendIndicators(ma_periods=(5, self.ma_fast, self.ma_slow, 60))
        self.last_signal_date = None  # 防止一天多次触发
        self.code = vt_symbol.split('.')[0]
        self.name = setting.get('name', self.code)
        self.entry_price = 0.0
        self.highest_since_entry = 0.0

    # vnpy 钩子
    def on_init(self):
        if HAS_VNPY:
            self.write_log(f"[trend_{self.code}] 策略初始化 {self.name}")
        # 加载历史数据初始化指标
        if HAS_VNPY:
            self.load_bar(60)

    def on_start(self):
        if HAS_VNPY:
            self.write_log(f"[trend_{self.code}] 策略启动")

    def on_stop(self):
        pass

    def on_bar(self, bar: BarData):
        """日线 bar 来时更新指标 + 决策"""
        self.indicators.update(bar.close_price, bar.high_price, bar.low_price, bar.volume)
        self._evaluate(bar.close_price, bar.volume, bar.high_price, bar.low_price)

    def on_tick(self, tick: TickData):
        """tick 不做交易，只更新当前价 + 跟踪止损（避免日内频繁触发）"""
        if not _is_trading_hours():
            return
        # 跟踪 highest_since_entry
        if self.pos > 0 and tick.last_price > self.highest_since_entry:
            self.highest_since_entry = tick.last_price

    def _evaluate(self, close: float, volume: float, high: float, low: float):
        """主要决策入口（在 on_bar 触发）"""
        today = datetime.now().date()
        if self.last_signal_date == today:
            return
        
        ind = self.indicators
        ma5 = ind.ma(5)
        ma_fast = ind.ma(self.ma_fast)
        ma_slow = ind.ma(self.ma_slow)
        n_high = ind.n_day_high(self.breakout_period)
        atr = ind.atr()
        rsi = ind.rsi()
        vol_avg = ind.vol_avg(5)

        # 数据没准备好
        if not all([ma5, ma_fast, ma_slow, n_high, atr, rsi, vol_avg]):
            return

        # ====== 入场信号（无持仓时） ======
        if self.pos == 0:
            # 1. 突破 N 日新高（前一日 high 都没破）
            prev_high = max(list(ind.highs)[:-1][-self.breakout_period:]) if len(ind.highs) > self.breakout_period else None
            if not prev_high:
                return
            
            cond_breakout = close > prev_high
            cond_vol = volume >= vol_avg * self.vol_ratio
            cond_ma_bullish = ma5 > ma_fast > ma_slow
            cond_rsi_ok = rsi < self.rsi_overbought
            
            if cond_breakout and cond_vol and cond_ma_bullish and cond_rsi_ok:
                self._signal_buy(close, atr, rsi, vol_avg, prev_high, volume)
                self.last_signal_date = today
                return
        
        # ====== 出场信号（持仓时） ======
        if self.pos > 0:
            # 1. ATR 止损
            stop_price = self.highest_since_entry - atr * self.atr_stop_x
            cond_atr_stop = close < stop_price
            
            # 2. 跌破 MA10
            cond_break_ma = close < ma_fast
            
            # 3. RSI 超买回落
            cond_rsi_overbought = rsi > self.rsi_overbought and close < self.indicators.closes[-2]
            
            if cond_atr_stop or cond_break_ma or cond_rsi_overbought:
                reason = []
                if cond_atr_stop:
                    reason.append(f'ATR止损({stop_price:.2f})')
                if cond_break_ma:
                    reason.append(f'破MA{self.ma_fast}({ma_fast:.2f})')
                if cond_rsi_overbought:
                    reason.append(f'RSI{rsi:.0f}超买回落')
                self._signal_sell(close, ' / '.join(reason))
                self.last_signal_date = today

    def _signal_buy(self, price, atr, rsi, vol_avg, prev_high, volume):
        msg = (
            f"[trend_{self.code}] 🚀 趋势买入信号 {self.name} @{price:.2f} "
            f"(突破 {prev_high:.2f}, 量 {volume/vol_avg:.1f}x, ATR {atr:.2f}, RSI {rsi:.0f})"
        )
        if HAS_VNPY:
            self.write_log(msg)
        else:
            logger.info(msg)
        
        # 调用 sim_executor 自动下单（限学习账户）
        if _sim_execute_trade and active_account_id and active_account_id() == 1:
            fake_rule = {
                'code': self.code,
                'name': self.name,
                'level': 'buy_zone',
                'message': f'趋势突破: 破 {prev_high:.2f}, 量{volume/vol_avg:.1f}x, RSI{rsi:.0f}',
            }
            result = _sim_execute_trade(fake_rule, price)
            if result.get('success'):
                self.entry_price = price
                self.highest_since_entry = price
                self.pos = result['trade']['qty']
                exec_msg = f"[trend_{self.code}] 💰 [trend_executor] {result['message']}"
                if HAS_VNPY:
                    self.write_log(exec_msg)

    def _signal_sell(self, price, reason: str):
        msg = (
            f"[trend_{self.code}] ⚠️ 趋势卖出信号 {self.name} @{price:.2f} "
            f"原因: {reason}"
        )
        if HAS_VNPY:
            self.write_log(msg)
        else:
            logger.info(msg)
        
        if _sim_execute_trade and active_account_id and active_account_id() == 1 and self.pos > 0:
            fake_rule = {
                'code': self.code,
                'name': self.name,
                'level': 'hard_stop',  # 复用 SELL_ALL
                'message': f'趋势出场: {reason}',
            }
            result = _sim_execute_trade(fake_rule, price)
            if result.get('success'):
                self.pos = 0
                self.entry_price = 0
                self.highest_since_entry = 0


if __name__ == '__main__':
    # 自检：跑一遍指标
    ind = TrendIndicators()
    import random
    random.seed(42)
    px = 10
    for i in range(30):
        px += random.uniform(-0.3, 0.4)
        ind.update(px, px + random.uniform(0, 0.2), px - random.uniform(0, 0.2),
                   random.uniform(50000, 100000))
    print(f'MA5: {ind.ma(5):.2f}')
    print(f'MA10: {ind.ma(10):.2f}')
    print(f'MA20: {ind.ma(20):.2f}')
    print(f'ATR: {ind.atr():.2f}')
    print(f'RSI: {ind.rsi():.2f}')
    print(f'vol_avg(5): {ind.vol_avg(5):.0f}')
    print(f'20日新高: {ind.n_day_high(20):.2f}')
