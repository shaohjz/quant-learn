"""
broker/base.py — 交易接口抽象基类

所有 broker（模拟/实盘）都必须实现这套 API。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date as Date
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class OrderResult:
    """订单执行结果"""
    success: bool
    msg: str = ""
    order_id: Optional[str] = None       # broker 端的委托号（实盘用）
    stock_code: str = ""
    side: Optional[OrderSide] = None
    price: float = 0.0
    quantity: int = 0
    amount: float = 0.0
    commission: float = 0.0
    tax: float = 0.0
    extra: dict = field(default_factory=dict)


@dataclass
class Position:
    stock_code: str
    stock_name: str
    quantity: int
    avg_cost: float
    current_price: float = 0.0
    market_value: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class Account:
    cash: float           # 可用资金
    total_value: float    # 总资产
    market_value: float = 0.0
    initial_cash: float = 0.0
    extra: dict = field(default_factory=dict)


class IBroker(ABC):
    """
    交易接口抽象基类。

    生命周期：
        __init__ → connect() → [buy/sell/...] → disconnect()
    """

    name: str = "abstract"

    # ---------- 生命周期 ----------
    @abstractmethod
    def connect(self) -> bool:
        """建立连接（实盘需要 connect 到 QMT；模拟盘可空实现返回 True）"""
        ...

    @abstractmethod
    def disconnect(self):
        """断开连接"""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        ...

    # ---------- 下单 ----------
    @abstractmethod
    def buy(self, stock_code: str, price: float, quantity: int,
            stock_name: str = "", signal_reason: str = "",
            trade_date: Optional[Date] = None) -> OrderResult:
        ...

    @abstractmethod
    def sell(self, stock_code: str, price: float, quantity: int,
             stock_name: str = "", signal_reason: str = "",
             trade_date: Optional[Date] = None) -> OrderResult:
        ...

    @abstractmethod
    def cancel(self, order_id: str) -> OrderResult:
        """撤单（实盘必须实现；模拟盘可返回 not supported）"""
        ...

    # ---------- 查询 ----------
    @abstractmethod
    def get_account(self) -> Account:
        ...

    @abstractmethod
    def get_positions(self) -> list[Position]:
        ...

    # ---------- 价格更新 / 结算（账本逻辑） ----------
    @abstractmethod
    def update_prices(self, price_dict: dict):
        """把最新价同步到本地账本（实盘可用于估算市值）"""
        ...

    @abstractmethod
    def daily_settle(self, trade_date: Optional[Date] = None) -> dict:
        """每日结算：刷新总资产、写当日净值"""
        ...
