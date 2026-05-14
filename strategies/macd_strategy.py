#!/usr/bin/env python3
"""
MACD 策略
- MACD 金叉（MACD线上穿信号线）→ 买入
- MACD 死叉（MACD线下穿信号线）→ 卖出
- 仓位管理：每次只用 50% 资金
"""

import backtrader as bt


class MacdStrategy(bt.Strategy):
    params = (
        ("fast_period", 12),    # 快线周期
        ("slow_period", 26),    # 慢线周期
        ("signal_period", 9),   # 信号线周期
        ("position_pct", 0.50), # 仓位比例 50%
    )

    def __init__(self):
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.fast_period,
            period_me2=self.p.slow_period,
            period_signal=self.p.signal_period,
        )
        # MACD 线与信号线的交叉
        self.crossover = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)

        self.order = None

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        # print(f"[{dt}] {txt}")

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f"买入 @ {order.executed.price:.2f}, 数量: {order.executed.size}")
            elif order.issell():
                self.log(f"卖出 @ {order.executed.price:.2f}")
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:
            # 无持仓：MACD 金叉买入（用 50% 资金）
            if self.crossover > 0:
                available_cash = self.broker.getcash() * self.p.position_pct
                size = int(available_cash / self.data.close[0])
                if size > 0:
                    # A股最小交易单位是100股（1手）
                    size = (size // 100) * 100
                    if size > 0:
                        self.order = self.buy(size=size)
        else:
            # 有持仓：MACD 死叉卖出
            if self.crossover < 0:
                self.order = self.sell(size=self.position.size)
