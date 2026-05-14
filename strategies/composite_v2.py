#!/usr/bin/env python3
"""
趋势+震荡自适应复合策略 (Composite V2)

先判断市场状态：
  - ADX > 25 → 趋势市（MACD + 均线跟趋势）
  - ADX <= 25 → 震荡市（RSI + 布林带高抛低吸）

趋势市买入：
  - MACD金叉 + 价格在20日均线上方 + ADX>25 + 成交量>均量

震荡市买入：
  - RSI<35 + 价格接近布林带下轨（距下轨<2%）+ 成交量未极度萎缩

统一风控：
  - 止损8%
  - 移动止盈（趋势市用15%回撤3%，震荡市用10%回撤2%）
  - 仓位：趋势市60%，震荡市40%
"""

import backtrader as bt


class CompositeV2Strategy(bt.Strategy):
    params = (
        # MACD
        ("macd_fast", 12),
        ("macd_slow", 26),
        ("macd_signal", 9),
        # RSI
        ("rsi_period", 14),
        ("rsi_oversold", 35),
        # Bollinger Bands
        ("bb_period", 20),
        ("bb_devfactor", 2.0),
        ("bb_proximity_pct", 0.02),  # 2% near lower band
        # ADX
        ("adx_period", 14),
        ("adx_trend_threshold", 25),
        # Moving Averages
        ("sma20_period", 20),
        # Volume
        ("vol_period", 20),
        ("vol_shrink_mult", 0.3),  # extreme shrink threshold
        # Risk management
        ("stop_loss_pct", 0.08),
        # Trend mode trailing stop
        ("trend_tp_threshold", 0.15),
        ("trend_tp_pullback", 0.03),
        # Range mode trailing stop
        ("range_tp_threshold", 0.10),
        ("range_tp_pullback", 0.02),
        # Position sizing
        ("trend_position_pct", 0.60),
        ("range_position_pct", 0.40),
        # Max hold
        ("max_hold_days", 30),
        ("printlog", True),
    )

    def __init__(self):
        # --- MACD ---
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.macd_fast,
            period_me2=self.p.macd_slow,
            period_signal=self.p.macd_signal,
        )
        self.macd_cross = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)

        # --- RSI ---
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)

        # --- Bollinger Bands ---
        self.boll = bt.indicators.BollingerBands(
            self.data.close,
            period=self.p.bb_period,
            devfactor=self.p.bb_devfactor,
        )

        # --- ADX ---
        self.adx = bt.indicators.AverageDirectionalMovementIndex(
            self.data, period=self.p.adx_period
        )

        # --- SMA 20 ---
        self.sma20 = bt.indicators.SMA(self.data.close, period=self.p.sma20_period)

        # --- Volume MA ---
        self.vol_ma = bt.indicators.SMA(self.data.volume, period=self.p.vol_period)

        # --- State ---
        self.order = None
        self.buy_price = None
        self.buy_date = None
        self.max_price_since_buy = None
        self.buy_mode = None  # "trend" or "range"
        self.buy_reason = ""
        self.sell_reason = ""

    def log(self, txt, dt=None):
        if self.p.printlog:
            dt = dt or self.datas[0].datetime.date(0)
            print(f"[{dt}] {txt}")

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_price = order.executed.price
                self.buy_date = len(self)
                self.max_price_since_buy = order.executed.price
                mode_label = "趋势" if self.buy_mode == "trend" else "震荡"
                self.log(f"✅ 买入 @ {order.executed.price:.2f}, 数量: {order.executed.size}, "
                         f"模式: {mode_label}, 原因: {self.buy_reason}")
            elif order.issell():
                if self.buy_price:
                    pnl = (order.executed.price - self.buy_price) / self.buy_price * 100
                    self.log(f"❌ 卖出 @ {order.executed.price:.2f}, 数量: {order.executed.size}, "
                             f"盈亏: {pnl:+.2f}%, 原因: {self.sell_reason}")
                else:
                    self.log(f"❌ 卖出 @ {order.executed.price:.2f}, 原因: {self.sell_reason}")
                self.buy_price = None
                self.buy_date = None
                self.max_price_since_buy = None
                self.buy_mode = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"⚠ 订单被取消/保证金不足/拒绝")
        self.order = None

    def _is_trend_market(self):
        """ADX > threshold means trending market"""
        return self.adx.adx[0] > self.p.adx_trend_threshold

    def _check_trend_buy(self):
        """Trend mode: MACD golden cross + price above SMA20 + ADX>25 + volume > avg"""
        signals = []
        if self.macd_cross[0] > 0:
            signals.append("MACD金叉")
        if self.data.close[0] > self.sma20[0]:
            signals.append("价>MA20")
        if self.adx.adx[0] > self.p.adx_trend_threshold:
            signals.append(f"ADX={self.adx.adx[0]:.1f}")
        if self.vol_ma[0] > 0 and self.data.volume[0] > self.vol_ma[0]:
            signals.append("放量")

        # All 4 conditions required
        if len(signals) == 4:
            return True, "+".join(signals)
        return False, ""

    def _check_range_buy(self):
        """Range mode: RSI<35 + price near lower BB + volume not extremely shrunk"""
        signals = []

        if self.rsi[0] < self.p.rsi_oversold:
            signals.append(f"RSI={self.rsi[0]:.1f}<{self.p.rsi_oversold}")

        # Price near lower Bollinger Band (within 2%)
        lower_band = self.boll.bot[0]
        if lower_band > 0:
            dist_pct = (self.data.close[0] - lower_band) / lower_band
            if dist_pct < self.p.bb_proximity_pct:
                signals.append(f"接近布林下轨({dist_pct*100:.1f}%)")

        # Volume not extremely shrunk
        if self.vol_ma[0] > 0 and self.data.volume[0] > self.vol_ma[0] * self.p.vol_shrink_mult:
            signals.append("量能未衰竭")

        # All 3 conditions required
        if len(signals) == 3:
            return True, "+".join(signals)
        return False, ""

    def _check_trend_sell(self):
        """Trend mode sell signals"""
        signals = []
        if self.macd_cross[0] < 0:
            signals.append("MACD死叉")
        if self.data.close[0] < self.sma20[0]:
            signals.append("价格跌破MA20")
        return signals

    def _check_range_sell(self):
        """Range mode sell signals"""
        signals = []
        upper_band = self.boll.top[0]
        if upper_band > 0:
            dist_pct = (upper_band - self.data.close[0]) / upper_band
            if dist_pct < self.p.bb_proximity_pct:
                signals.append("接近布林上轨")
        if self.rsi[0] > 70:
            signals.append(f"RSI={self.rsi[0]:.1f}>70")
        return signals

    def next(self):
        if self.order:
            return

        is_trend = self._is_trend_market()

        if not self.position:
            # --- No position: check buy signals ---
            if is_trend:
                ok, reason = self._check_trend_buy()
                if ok:
                    pos_pct = self.p.trend_position_pct
                    self.buy_mode = "trend"
                    self.buy_reason = f"[趋势]{reason}"
                    available_cash = self.broker.getcash() * pos_pct
                    size = int(available_cash / self.data.close[0])
                    size = (size // 100) * 100
                    if size > 0:
                        self.order = self.buy(size=size)
            else:
                ok, reason = self._check_range_buy()
                if ok:
                    pos_pct = self.p.range_position_pct
                    self.buy_mode = "range"
                    self.buy_reason = f"[震荡]{reason}"
                    available_cash = self.broker.getcash() * pos_pct
                    size = int(available_cash / self.data.close[0])
                    size = (size // 100) * 100
                    if size > 0:
                        self.order = self.buy(size=size)
        else:
            # --- Has position ---
            if self.max_price_since_buy is not None:
                self.max_price_since_buy = max(self.max_price_since_buy, self.data.close[0])

            if self.buy_price:
                current_price = self.data.close[0]
                pnl_pct = (current_price - self.buy_price) / self.buy_price
                hold_days = len(self) - self.buy_date if self.buy_date else 0

                # Stop loss: 8%
                if pnl_pct <= -self.p.stop_loss_pct:
                    self.sell_reason = f"止损({pnl_pct*100:.1f}%)"
                    self.order = self.sell(size=self.position.size)
                    return

                # Trailing take profit (depends on buy mode)
                if self.buy_mode == "trend":
                    tp_threshold = self.p.trend_tp_threshold
                    tp_pullback = self.p.trend_tp_pullback
                else:
                    tp_threshold = self.p.range_tp_threshold
                    tp_pullback = self.p.range_tp_pullback

                if self.max_price_since_buy and pnl_pct >= tp_threshold:
                    pullback = (self.max_price_since_buy - current_price) / self.max_price_since_buy
                    if pullback >= tp_pullback:
                        self.sell_reason = (f"移动止盈(盈{pnl_pct*100:.1f}%,"
                                           f"回撤{pullback*100:.1f}%,"
                                           f"模式={'趋势' if self.buy_mode=='trend' else '震荡'})")
                        self.order = self.sell(size=self.position.size)
                        return

                # Max hold days
                if hold_days >= self.p.max_hold_days and pnl_pct <= 0:
                    self.sell_reason = f"持仓超{self.p.max_hold_days}天无盈利"
                    self.order = self.sell(size=self.position.size)
                    return

            # Signal-based sell
            if self.buy_mode == "trend":
                sell_signals = self._check_trend_sell()
                # In trend mode, need 1 signal to sell (trend break is significant)
                if len(sell_signals) >= 1:
                    self.sell_reason = "+".join(sell_signals)
                    self.order = self.sell(size=self.position.size)
            else:
                sell_signals = self._check_range_sell()
                # In range mode, need 1 signal (reaching upper band or RSI overbought)
                if len(sell_signals) >= 1:
                    self.sell_reason = "+".join(sell_signals)
                    self.order = self.sell(size=self.position.size)
