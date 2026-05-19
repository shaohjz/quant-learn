"""gateways 包：vnpy 网关层。

目前实现：
- QmtGateway: 轻量自封装的国金 QMT mini 网关（基于 xtquant 直连）
"""
from .qmt_gateway import QmtGateway, FORBIDDEN_ACCOUNTS  # noqa: F401
