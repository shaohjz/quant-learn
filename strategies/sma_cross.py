#!/usr/bin/env python3
"""
双均线交叉策略 (SMA Cross)
- 短期均线上穿长期均线 → 买入
- 短期均线下穿长期均线 → 卖出
- 10% 止损
"""

import backtrader as bt


class SmaCross(bt.Strategy):
    params = (
        ("short_period", 5),   # 短期均线周期
        ("long_period", 20),   # 长期均线周期
        ("stop_loss", 0.10),   # 止损比例 10%
    )

    def __init__(self):
        self.sma_short = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.short_period
        )
        self.sma_long = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.long_period
        )
        self.crossover = bt.indicators.CrossOver(self.sma_short, self.sma_long)

        # 记录订单和买入价格
        self.order = None
        self.buy_price = None

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        # print(f"[{dt}] {txt}")  # 取消注释可打印日志

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_price = order.executed.price
                self.log(f"买入 @ {order.executed.price:.2f}")
            elif order.issell():
                self.log(f"卖出 @ {order.executed.price:.2f}")
                self.buy_price = None
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:
            # 无持仓：金叉买入
            if self.crossover > 0:
                self.order = self.buy()
        else:
            # 有持仓
            # 止损检查
            if self.buy_price and self.data.close[0] < self.buy_price * (1 - self.p.stop_loss):
                self.order = self.sell()
                return
            # 死叉卖出
            if self.crossover < 0:
                self.order = self.sell()
