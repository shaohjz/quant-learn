"""
broker/factory.py — broker 工厂

根据 mode 字符串返回合适的 broker 实例。
"""

import os
from .base import IBroker
from .sim_broker import SimBroker


def get_broker(mode: str = "sim", **kwargs) -> IBroker:
    """
    :param mode: "sim" / "live" / "qmt"
    :param kwargs: 传递给具体 broker 的参数
    :return: 已 connect 的 IBroker 实例
    """
    mode = (mode or "sim").lower()

    if mode == "sim":
        broker = SimBroker(
            account_id=int(kwargs.get("account_id", 1)),
            slippage=float(kwargs.get("slippage", 0.0)),
        )
    elif mode in ("live", "qmt"):
        from .qmt_broker import QMTBroker
        qmt_path = kwargs.get("qmt_path") or os.environ.get("QMT_USERDATA_MINI")
        account_id = kwargs.get("qmt_account") or os.environ.get("QMT_ACCOUNT_ID")
        if not qmt_path or not account_id:
            raise RuntimeError(
                "实盘模式需要设置 QMT_USERDATA_MINI 和 QMT_ACCOUNT_ID 环境变量，"
                "或在调用时传 qmt_path 和 qmt_account 参数"
            )
        broker = QMTBroker(
            qmt_path=qmt_path,
            account_id=account_id,
            session_id=int(kwargs.get("session_id", os.environ.get("QMT_SESSION_ID", "123456"))),
            local_account_id=int(kwargs.get("account_id", 1)),
        )
    else:
        raise ValueError(f"未知的 broker mode: {mode}")

    broker.connect()
    return broker
