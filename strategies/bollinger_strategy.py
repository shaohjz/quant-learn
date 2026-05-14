#!/usr/bin/env python3
"""
布林带策略 (Bollinger Bands)
- 价格触及下轨 → 买入
- 价格触及上轨 → 卖出
- 中轨止损（价格跌破中轨平仓）
"""

import backtrader as bt


class BollingerStrategy(bt.Strategy):
    params = (
        ("period", 20),     # 布林带周期
        ("devfactor", 2),   # 标准差倍数
    )

    def __init__(self):
        self.boll = bt.indicators.BollingerBands(
            self.data.close,
            period=self.p.period,
            devfactor=self.p.devfactor,
        )
        self.order = None

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        # print(f"[{dt}] {txt}")

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f"买入 @ {order.executed.price:.2f}")
            elif order.issell():
                self.log(f"卖出 @ {order.executed.price:.2f}")
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:
            # 无持仓：价格触及或跌破下轨 → 买入
            if self.data.close[0] <= self.boll.lines.bot[0]:
                self.order = self.buy()
        else:
            # 有持仓
            # 价格触及或突破上轨 → 卖出止盈
            if self.data.close[0] >= self.boll.lines.top[0]:
                self.order = self.sell()
            # 价格跌破中轨 → 止损
            elif self.data.close[0] < self.boll.lines.mid[0]:
                self.order = self.sell()
