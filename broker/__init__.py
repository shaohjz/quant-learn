"""
broker/ — 交易接口抽象层

设计理念：
- IBroker：抽象基类，定义模拟盘和实盘必须实现的同一套 API
- SimBroker：模拟盘实现，复用 sim/engine 的账本逻辑
- QMTBroker：实盘实现（占位，等 QMT 客户端装好后补完）

上层（run_daily.py）只关心 IBroker 接口，不关心具体是模拟还是实盘。
切换实盘只需改一行配置（mode=sim -> mode=live）。
"""

from .base import IBroker, OrderResult, OrderSide
from .sim_broker import SimBroker
from .factory import get_broker

__all__ = ["IBroker", "OrderResult", "OrderSide", "SimBroker", "get_broker"]
