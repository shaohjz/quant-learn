"""gateways 包：行情/交易网关层。

目前实现：
- RealtimePriceGateway: 多数据源实时行情（BaoStock 主源 + AKShare 备选）
- QmtGateway: 轻量自封装的国金 QMT mini 网关（基于 xtquant 直连，可选依赖 vnpy）
"""
from .realtime_price_gateway import RealtimePriceGateway  # noqa: F401

# QmtGateway 依赖 vnpy，可选导入
try:
    from .qmt_gateway import QmtGateway, FORBIDDEN_ACCOUNTS  # noqa: F401
except ImportError:
    # vnpy 未安装时，QmtGateway 不可用（当前 broker.mode=sim，不影响使用）
    pass
