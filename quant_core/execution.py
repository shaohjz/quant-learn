"""
quant_core/execution.py — 真实执行模拟和A股约束

QL-007: 修复同bar收盘成交，统一回测/Paper的成交规则。

设计要点:
  - 默认模式: T日收盘信号，最早T+1开盘成交
  - 允许显式配置 next_open / next_vwap 等模式
  - 禁止隐式同bar close
  - A股约束: T+1可卖、100股买入单位、涨跌停不可成交、停牌
  - 每笔Fill记录 signal_time, submit_time, fill_time, price_source
  - 无IO副作用
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date, datetime
from typing import Optional

from .domain import (
    Bar, Direction, OrderSide, OrderType, Fill, FillSource,
    OrderIntent, PriceSource,
)
from .fees import FeeModel


@dataclass
class ExecutionConfig:
    """执行配置"""
    default_price_source: PriceSource = PriceSource.NEXT_OPEN
    allow_same_bar: bool = False      # 禁止隐式同bar close
    slippage_pct: float = 0.0         # 滑点百分比
    volume_participation: float = 0.05 # 成交量参与率上限
    min_trade_unit: int = 100         # A股最小交易单位


class ExecutionPolicy:
    """执行策略 — 从 OrderIntent 生成 Fill

    核心约束:
      1. T日信号 → 最早T+1成交
      2. 100股买入单位 & 零股卖出
      3. 涨停买不到、跌停卖不出
      4. 停牌不可成交
      5. 成交量参与率限制
      6. 买卖方向滑点
    """

    def __init__(self, config: Optional[ExecutionConfig] = None,
                 fee_model: Optional[FeeModel] = None):
        self._config = config or ExecutionConfig()
        self._fee_model = fee_model or FeeModel()

    def execute(
        self,
        intent: OrderIntent,
        next_bar: Optional[Bar] = None,
        portfolio_holdings: Optional[dict[str, int]] = None,
        signal_date: Optional[Date] = None,
        trade_date: Optional[Date] = None,
    ) -> Optional[Fill]:
        """从 OrderIntent 生成 Fill（或 None 表示无法成交）

        :param intent: 下单意图
        :param next_bar: T+1 的行情数据（用于确定成交价和涨跌停）
        :param portfolio_holdings: 当前持仓 {symbol: quantity}（用于T+1可卖检查）
        :param signal_date: 信号日期
        :param trade_date: 交易日期
        """
        if next_bar is None:
            return None  # 无行情数据，无法成交

        # ─── 1. T+1 约束 ───
        if signal_date and trade_date and trade_date <= signal_date:
            # QL-007 核心约束: T日信号绝不在T日成交
            return None

        # ─── 2. 停牌检查 ───
        if next_bar.volume <= 0:
            return None  # 停牌无成交

        # ─── 3. 涨跌停检查 ───
        price = self._determine_price(intent, next_bar)
        if price is None:
            return None

        # ─── 4. 成交量参与率 ───
        max_volume = next_bar.volume * self._config.volume_participation
        quantity = min(intent.quantity, int(max_volume))

        # ─── 5. 100股买入单位 ───
        if intent.side == OrderSide.BUY:
            quantity = (quantity // self._config.min_trade_unit) * self._config.min_trade_unit
            if quantity <= 0:
                return None  # 买不到一手

        # ─── 6. T+1可卖约束（卖出时） ───
        if intent.side == OrderSide.SELL and portfolio_holdings:
            available = portfolio_holdings.get(intent.symbol, 0)
            quantity = min(quantity, available)
            if quantity <= 0:
                return None

        # ─── 7. 滑点 ───
        if self._config.slippage_pct > 0:
            if intent.side == OrderSide.BUY:
                price *= (1 + self._config.slippage_pct)
            else:
                price *= (1 - self._config.slippage_pct)

        amount = price * quantity

        # ─── 8. 费用 ───
        fees = self._fee_model.calculate(
            side=intent.side.value,
            amount=amount,
            trade_date=trade_date,
            exchange=next_bar.exchange,
        )

        return Fill(
            symbol=intent.symbol,
            side=intent.side,
            quantity=quantity,
            price=round(price, 3),
            amount=round(amount, 2),
            commission=fees.commission,
            stamp_tax=fees.stamp_tax,
            transfer_fee=fees.transfer_fee,
            source=FillSource.BACKTEST,
            price_source=self._config.default_price_source,
            signal_time=intent.signal_time,
            submit_time=intent.submit_time or datetime.now(),
            fill_time=datetime.now(),
            order_id=intent.order_id if hasattr(intent, 'order_id') else None,
        )

    def _determine_price(self, intent: OrderIntent, bar: Bar) -> Optional[float]:
        """确定成交价 — 考虑涨跌停"""
        if self._config.default_price_source == PriceSource.NEXT_OPEN:
            # 涨停: open == high == upper_limit，买入可能无法成交
            # 简化判断: 如果 open == high 且涨幅接近10%，视为涨停
            if intent.side == OrderSide.BUY and bar.open > 0 and bar.close > 0:
                pct_change = (bar.close - bar.open) / bar.open if bar.open > 0 else 0
                # 如果收盘涨幅 > 9.5% 视为涨停（简化）
                if pct_change > 0.095:
                    return None  # 涨停买不到
            # 跌停: 卖出可能无法成交
            if intent.side == OrderSide.SELL and bar.open > 0 and bar.close > 0:
                pct_change = (bar.close - bar.open) / bar.open if bar.open > 0 else 0
                if pct_change < -0.095:
                    return None  # 跌停卖不出
            return bar.open

        elif self._config.default_price_source == PriceSource.NEXT_VWAP:
            # VWAP 近似用 (open + high + low + close) / 4
            return (bar.open + bar.high + bar.low + bar.close) / 4

        elif self._config.default_price_source == PriceSource.CLOSE:
            # Legacy: 不应在新代码中使用
            return bar.close

        return bar.open


def validate_execution_timing(signal_date: Date, fill_date: Date) -> bool:
    """验证执行时序 — T日信号最早T+1成交

    Returns True if valid (fill_date > signal_date), False otherwise.
    """
    return fill_date > signal_date
