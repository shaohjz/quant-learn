"""
vqlearn/strategies/threshold_strategy.py — 阈值告警策略

替代旧的 portfolio_alert.py 的 RULES 字典逻辑。
继承 vnpy CtaTemplate（兼容回测/实盘）。

每只股票配置一组规则：
- buy_zone:    回调到位价（建议买入信号）
- buy_strong:  深度回调价（强买入信号 → 自动下单）
- trend_break: 趋势破位价（卖出信号 → 自动下单）
- take_profit: 止盈价

触发逻辑：
- on_tick 检查每只股票当前价
- 同一规则当日只触发一次（去重）
- 触发后通过 self.buy()/self.sell() 走 vnpy OMS
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from vnpy_ctastrategy import CtaTemplate, StopOrder
from vnpy.trader.object import TickData, BarData, OrderData, TradeData


class ThresholdAlertStrategy(CtaTemplate):
    """单只股票的阈值告警策略"""

    author = "vqlearn"

    # 参数（每只股票实例化时通过 setting 传入）
    buy_zone = 0.0          # 回调买入价
    buy_strong = 0.0        # 深度回调价（强买入）
    trend_break = 0.0       # 跌破止损价
    take_profit = 0.0       # 止盈价
    fixed_size = 100        # 每次下单数量
    auto_trade = False      # 是否自动下单（False=只告警不下单）

    parameters = ["buy_zone", "buy_strong", "trend_break", "take_profit", "fixed_size", "auto_trade"]
    variables = ["last_price", "fired_today"]

    def __init__(self, cta_engine: Any, strategy_name: str, vt_symbol: str, setting: dict) -> None:
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.last_price = 0.0
        self.fired_today: dict[str, str] = {}  # rule_name -> date

    # ----- vnpy lifecycle -----
    def on_init(self) -> None:
        self.write_log(f"策略初始化: {self.vt_symbol}")
        self.write_log(
            f"  规则: buy_zone={self.buy_zone} buy_strong={self.buy_strong} "
            f"trend_break={self.trend_break} take_profit={self.take_profit} auto={self.auto_trade}"
        )

    def on_start(self) -> None:
        self.write_log(f"策略启动: {self.vt_symbol}")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log(f"策略停止: {self.vt_symbol}")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        self.last_price = tick.last_price
        self._check_rules(tick)
        self.put_event()

    def on_bar(self, bar: BarData) -> None:
        self.last_price = bar.close_price
        # 复盘时按 bar 检查
        fake_tick = TickData(
            gateway_name=bar.gateway_name,
            symbol=bar.symbol,
            exchange=bar.exchange,
            datetime=bar.datetime,
            last_price=bar.close_price,
        )
        self._check_rules(fake_tick)

    def on_order(self, order: OrderData) -> None:
        self.write_log(f"订单更新: {order.symbol} {order.direction.value} {order.volume}@{order.price:.2f} {order.status.value}")

    def on_trade(self, trade: TradeData) -> None:
        self.write_log(f"💰 成交: {trade.symbol} {trade.direction.value} {trade.volume}@{trade.price:.2f}")
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass

    # ----- 规则检查 -----
    def _check_rules(self, tick: TickData) -> None:
        today = tick.datetime.strftime("%Y-%m-%d") if tick.datetime else datetime.now().strftime("%Y-%m-%d")
        price = tick.last_price

        # 1. trend_break: 跌破 → SELL
        if self.trend_break > 0 and price <= self.trend_break:
            if self.fired_today.get("trend_break") != today:
                self.fired_today["trend_break"] = today
                self.write_log(f"🔴 [trend_break] {self.vt_symbol} {price:.2f} <= {self.trend_break:.2f}")
                if self.auto_trade and self.pos > 0:
                    sell_volume = min(self.pos, self.fixed_size)
                    self.sell(price * 0.99, sell_volume)

        # 2. buy_strong: 深度回调 → BUY (强)
        elif self.buy_strong > 0 and price <= self.buy_strong:
            if self.fired_today.get("buy_strong") != today:
                self.fired_today["buy_strong"] = today
                self.write_log(f"🟢🟢 [buy_strong] {self.vt_symbol} {price:.2f} <= {self.buy_strong:.2f}")
                if self.auto_trade:
                    self.buy(price * 1.01, self.fixed_size)

        # 3. buy_zone: 回调到位 → BUY (轻仓)
        elif self.buy_zone > 0 and price <= self.buy_zone:
            if self.fired_today.get("buy_zone") != today:
                self.fired_today["buy_zone"] = today
                self.write_log(f"🟢 [buy_zone] {self.vt_symbol} {price:.2f} <= {self.buy_zone:.2f}")
                if self.auto_trade:
                    self.buy(price * 1.01, self.fixed_size // 2)

        # 4. take_profit: 涨到止盈 → SELL
        if self.take_profit > 0 and price >= self.take_profit:
            if self.fired_today.get("take_profit") != today:
                self.fired_today["take_profit"] = today
                self.write_log(f"🟡 [take_profit] {self.vt_symbol} {price:.2f} >= {self.take_profit:.2f}")
                if self.auto_trade and self.pos > 0:
                    sell_volume = min(self.pos, self.fixed_size)
                    self.sell(price * 0.99, sell_volume)
