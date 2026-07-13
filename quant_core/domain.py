"""
quant_core/domain.py — 核心领域模型

QL-006 / QL-008: 统一 Bar、SignalIntent、OrderIntent、Fill、Position 等领域对象。
所有对象为纯数据类，无IO副作用。

设计要点:
  - Bar 包含: symbol, exchange, timestamp, OHLCV, raw/adjusted 标识, 数据可见时间, source
  - SignalIntent 只描述方向、目标、置信度、理由和生效时间，不直接下单
  - 执行使用未复权真实价格，特征使用调整后序列，两者由同一 adjustment factor 对齐
  - Fill 记录 signal_time, submit_time, fill_time, price_source
  - 阈值保存 effective_from/effective_to/calculated_at/input_end_time
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date as Date
from enum import Enum
from typing import Optional


# ─── Enums ───
class Direction(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class FillSource(Enum):
    SIM = "sim"
    QMT = "qmt"
    BACKTEST = "backtest"
    DRY_RUN = "dry_run"


class PriceSource(Enum):
    NEXT_OPEN = "next_open"
    NEXT_VWAP = "next_vwap"
    CLOSE = "close"       # 仅用于标记legacy回测
    MARKET = "market"


class AdjustmentType(Enum):
    RAW = "raw"           # 未复权真实价格（执行用）
    FORWARD = "forward"   # 前复权（特征计算用）
    BACKWARD = "backward" # 后复权


# ─── Bar ───
@dataclass
class Bar:
    """行情数据 — Point-in-time 核心"""
    symbol: str
    exchange: str                    # "SH" / "SZ"
    timestamp: datetime              # 行情时间
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0             # 成交额
    adjustment_type: AdjustmentType = AdjustmentType.RAW
    adjustment_factor: float = 1.0  # 复权因子：raw_price * factor = adjusted_price
    data_visible_time: Optional[datetime] = None  # 数据何时对策略可见（防止未来数据）
    source: str = "unknown"         # 数据来源标识

    @property
    def adjusted_close(self) -> float:
        """前复权收盘价"""
        return self.close * self.adjustment_factor

    @property
    def raw_close(self) -> float:
        """未复权真实收盘价（执行用）"""
        return self.close


# ─── SignalIntent ───
@dataclass
class SignalIntent:
    """策略信号意图 — 只描述方向和目标，不直接下单

    QL-008: 同一输入在回测、Paper、QMT 生成相同 SignalIntent
    """
    symbol: str
    direction: Direction
    confidence: float = 0.0          # 0~1
    reason: str = ""
    effective_time: Optional[datetime] = None
    target_price: Optional[float] = None
    stop_price: Optional[float] = None
    as_of: Optional[Date] = None     # 信号基于哪天的数据

    # 阈值追溯信息（QL-006: 防止拿当前阈值回放过去）
    threshold_effective_from: Optional[Date] = None
    threshold_effective_to: Optional[Date] = None
    threshold_calculated_at: Optional[datetime] = None
    threshold_input_end_time: Optional[Date] = None


# ─── OrderIntent ───
@dataclass
class OrderIntent:
    """下单意图 — 从 SignalIntent 到执行的中间状态"""
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: float                     # 目标价格（真实可交易价格，非复权）
    signal_intent: Optional[SignalIntent] = None
    portfolio_state_id: Optional[str] = None  # 关联组合状态

    # 时点记录
    signal_time: Optional[datetime] = None   # 信号产生时间
    submit_time: Optional[datetime] = None    # 下单提交时间


# ─── Fill ───
@dataclass
class Fill:
    """成交记录"""
    symbol: str
    side: OrderSide
    quantity: int
    price: float
    amount: float = 0.0
    commission: float = 0.0
    stamp_tax: float = 0.0
    transfer_fee: float = 0.0
    source: FillSource = FillSource.SIM
    price_source: PriceSource = PriceSource.NEXT_OPEN

    # 关键时点（QL-007: 禁止T日信号T日成交）
    signal_time: Optional[datetime] = None
    submit_time: Optional[datetime] = None
    fill_time: Optional[datetime] = None

    order_id: Optional[str] = None
    estimated: bool = False          # QMT实际费用不可得时标记


# ─── Position ───
@dataclass
class PositionSnapshot:
    """持仓快照"""
    symbol: str
    quantity: int
    avg_cost: float
    current_price: float = 0.0
    market_value: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    trailing_stop_price: Optional[float] = None
    highest_price: Optional[float] = None


# ─── Threshold ───
@dataclass
class Threshold:
    """阈值记录 — Point-in-time 核心

    禁止拿当前阈值回放过去：
    - effective_from/effective_to: 此阈值生效的时间范围
    - calculated_at: 阈值计算时间
    - input_end_time: 计算输入数据的截止时间
    """
    symbol: str
    threshold_type: str              # "buy_zone", "buy_strong", "trend_break", etc.
    value: float
    direction: str                   # "above" / "below"
    effective_from: Optional[Date] = None
    effective_to: Optional[Date] = None
    calculated_at: Optional[datetime] = None
    input_end_time: Optional[Date] = None
    message: str = ""
