#!/usr/bin/env python3
"""
多指标复合策略 (Composite Strategy)

核心思路：多指标投票/确认机制，信号一致才开仓

买入条件（至少满足3个）：
  1. MACD金叉（DIF上穿DEA）
  2. RSI从超卖区回升（RSI<30后回到30以上，或RSI从40以下上穿40）
  3. 成交量放大（当日成交量 > 过去20日均量的1.5倍）
  4. 价格站上5日均线且5日均线拐头向上
  5. KDJ金叉（K线上穿D线，且J值<80）

卖出条件（满足2个即卖）：
  1. MACD死叉
  2. RSI进入超买区（>70）后回落跌破70
  3. 价格跌破10日均线
  4. KDJ死叉且J值>80
  5. 成交量萎缩至20日均量的0.5倍以下（量能衰竭）

风控规则：
  - 单次开仓不超过总资金的60%
  - 止损：买入价下方8%
  - 止盈：浮盈超过20%后，回撤5%则止盈（移动止盈）
  - 最大持仓时间30个交易日（超时无盈利则平仓）
"""

import backtrader as bt


class CompositeStrategy(bt.Strategy):
    params = (
        ("macd_fast", 12),
        ("macd_slow", 26),
        ("macd_signal", 9),
        ("rsi_period", 14),
        ("rsi_oversold", 30),
        ("rsi_overbought", 70),
        ("rsi_mid", 40),
        ("vol_period", 20),
        ("vol_mult_buy", 1.5),
        ("vol_mult_sell", 0.5),
        ("sma_short", 5),
        ("sma_mid", 10),
        ("stoch_period", 14),
        ("stoch_period_dfast", 3),
        ("stoch_period_dslow", 3),
        ("kdj_j_buy_max", 80),
        ("kdj_j_sell_min", 80),
        ("buy_signals_required", 3),
        ("sell_signals_required", 2),
        ("position_pct", 0.60),
        ("stop_loss_pct", 0.08),
        ("trailing_profit_threshold", 0.20),
        ("trailing_profit_pullback", 0.05),
        ("max_hold_days", 30),
        ("printlog", True),
    )

    def __init__(self):
        # --- Indicators ---
        # MACD
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.macd_fast,
            period_me2=self.p.macd_slow,
            period_signal=self.p.macd_signal,
        )
        self.macd_cross = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)

        # RSI
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)

        # Volume MA
        self.vol_ma = bt.indicators.SMA(self.data.volume, period=self.p.vol_period)

        # SMA 5 and 10
        self.sma5 = bt.indicators.SMA(self.data.close, period=self.p.sma_short)
        self.sma10 = bt.indicators.SMA(self.data.close, period=self.p.sma_mid)

        # KDJ (Stochastic)
        self.stoch = bt.indicators.Stochastic(
            self.data,
            period=self.p.stoch_period,
            period_dfast=self.p.stoch_period_dfast,
            period_dslow=self.p.stoch_period_dslow,
        )
        # K = percK, D = percD, J = 3*K - 2*D
        self.kdj_cross = bt.indicators.CrossOver(self.stoch.percK, self.stoch.percD)

        # --- State ---
        self.order = None
        self.buy_price = None
        self.buy_date = None
        self.max_price_since_buy = None
        self.buy_reason = ""
        self.sell_reason = ""

        # RSI state tracking
        self.rsi_was_oversold = False
        self.rsi_was_overbought = False

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
                self.log(f"✅ 买入 @ {order.executed.price:.2f}, 数量: {order.executed.size}, "
                         f"原因: {self.buy_reason}")
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
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"⚠ 订单被取消/保证金不足/拒绝")
        self.order = None

    def _j_value(self):
        """Calculate J value: 3*K - 2*D"""
        return 3 * self.stoch.percK[0] - 2 * self.stoch.percD[0]

    def _count_buy_signals(self):
        """Count how many buy signals are active"""
        signals = []

        # 1. MACD golden cross
        if self.macd_cross[0] > 0:
            signals.append("MACD金叉")

        # 2. RSI recovery from oversold
        if self.rsi[0] < self.p.rsi_oversold:
            self.rsi_was_oversold = True
        if self.rsi_was_oversold and self.rsi[0] > self.p.rsi_oversold:
            signals.append("RSI超卖回升")
            self.rsi_was_oversold = False
        elif len(self.rsi) > 1 and self.rsi[-1] < self.p.rsi_mid and self.rsi[0] >= self.p.rsi_mid:
            signals.append("RSI上穿40")

        # 3. Volume expansion
        if self.vol_ma[0] > 0 and self.data.volume[0] > self.vol_ma[0] * self.p.vol_mult_buy:
            signals.append("放量")

        # 4. Price above SMA5 and SMA5 turning up
        if (self.data.close[0] > self.sma5[0] and
                len(self.sma5) > 1 and self.sma5[0] > self.sma5[-1]):
            signals.append("站上MA5且MA5拐头")

        # 5. KDJ golden cross with J < 80
        j_val = self._j_value()
        if self.kdj_cross[0] > 0 and j_val < self.p.kdj_j_buy_max:
            signals.append("KDJ金叉")

        return signals

    def _count_sell_signals(self):
        """Count how many sell signals are active"""
        signals = []

        # 1. MACD death cross
        if self.macd_cross[0] < 0:
            signals.append("MACD死叉")

        # 2. RSI overbought and falling below 70
        if self.rsi[0] > self.p.rsi_overbought:
            self.rsi_was_overbought = True
        if self.rsi_was_overbought and self.rsi[0] < self.p.rsi_overbought:
            signals.append("RSI超买回落")
            self.rsi_was_overbought = False

        # 3. Price below SMA10
        if self.data.close[0] < self.sma10[0]:
            signals.append("跌破MA10")

        # 4. KDJ death cross with J > 80
        j_val = self._j_value()
        if self.kdj_cross[0] < 0 and j_val > self.p.kdj_j_sell_min:
            signals.append("KDJ死叉")

        # 5. Volume shrink
        if self.vol_ma[0] > 0 and self.data.volume[0] < self.vol_ma[0] * self.p.vol_mult_sell:
            signals.append("缩量")

        return signals

    def next(self):
        if self.order:
            return

        if not self.position:
            # --- No position: check buy signals ---
            buy_signals = self._count_buy_signals()
            if len(buy_signals) >= self.p.buy_signals_required:
                available_cash = self.broker.getcash() * self.p.position_pct
                size = int(available_cash / self.data.close[0])
                size = (size // 100) * 100  # Round to 100 shares
                if size > 0:
                    self.buy_reason = "+".join(buy_signals)
                    self.order = self.buy(size=size)
        else:
            # Update max price since buy (for trailing stop)
            if self.max_price_since_buy is not None:
                self.max_price_since_buy = max(self.max_price_since_buy, self.data.close[0])

            # --- Risk management checks ---
            if self.buy_price:
                current_price = self.data.close[0]
                pnl_pct = (current_price - self.buy_price) / self.buy_price
                hold_days = len(self) - self.buy_date if self.buy_date else 0

                # Stop loss: 8%
                if pnl_pct <= -self.p.stop_loss_pct:
                    self.sell_reason = f"止损({pnl_pct*100:.1f}%)"
                    self.order = self.sell(size=self.position.size)
                    return

                # Trailing take profit: after +20%, pullback 5% from peak
                if self.max_price_since_buy and pnl_pct >= self.p.trailing_profit_threshold:
                    pullback = (self.max_price_since_buy - current_price) / self.max_price_since_buy
                    if pullback >= self.p.trailing_profit_pullback:
                        self.sell_reason = f"移动止盈(盈{pnl_pct*100:.1f}%,回撤{pullback*100:.1f}%)"
                        self.order = self.sell(size=self.position.size)
                        return

                # Max hold days: exit if no profit after 30 days
                if hold_days >= self.p.max_hold_days and pnl_pct <= 0:
                    self.sell_reason = f"持仓超{self.p.max_hold_days}天无盈利"
                    self.order = self.sell(size=self.position.size)
                    return

            # --- Signal-based sell ---
            sell_signals = self._count_sell_signals()
            if len(sell_signals) >= self.p.sell_signals_required:
                self.sell_reason = "+".join(sell_signals)
                self.order = self.sell(size=self.position.size)
