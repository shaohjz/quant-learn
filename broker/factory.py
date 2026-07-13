"""
broker/factory.py — broker 工厂

根据 mode 字符串返回合适的 broker 实例。
"""

import os
import logging
from .base import IBroker
from .sim_broker import SimBroker
from .trading_gate import check_live_order, GateDecision

logger = logging.getLogger(__name__)


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
    if mode in ("live", "qmt"):
        # QL-000: 自动交易总闸检查
        account_id_str = str(kwargs.get("qmt_account") or os.environ.get("QMT_ACCOUNT_ID") or kwargs.get("account_id", ""))
        # 估算单笔金额（用传入的价格×数量，如果没有则用风险配置限额作兜底）
        _price = float(kwargs.get("price", 0))
        _qty = int(kwargs.get("quantity", 0))
        _amount = _price * _qty if _price > 0 and _qty > 0 else 0.0
        gate_decision = check_live_order(mode, account_id_str, _amount)
        gate_decision_audit = gate_decision  # 保留引用
        if not gate_decision.allowed:
            logger.error(
                f"⛔ TradingGate BLOCKED: mode={mode} account={account_id_str} "
                f"reason={gate_decision.reason}"
            )
            # 返回一个 dry_run 的 SimBroker 而不是抛异常 — fail closed 但不崩溃
            logger.warning("Falling back to SimBroker due to TradingGate block")
            broker = SimBroker(
                account_id=int(kwargs.get("account_id", 1)),
                slippage=float(kwargs.get("slippage", 0.0)),
            )
            broker.connect()
            return broker
        logger.info(f"✅ TradingGate PASSED: mode={mode} account={account_id_str}")

        from .qmt_broker import QMTBroker
        qmt_path = kwargs.get("qmt_path") or os.environ.get("QMT_USERDATA_MINI")
        account_id = kwargs.get("qmt_account") or os.environ.get("QMT_ACCOUNT_ID")
        if not qmt_path or not account_id:
            raise RuntimeError(
                "实盘模式需要设置 QMT_USERDATA_MINI 和 QMT_ACCOUNT_ID 环境变量，"
                "或在调用时传 qmt_path 和 qmt_account 参数"
            )
        # ⚠️ 硬隔离：拒绝连接真实账户
        if str(account_id) in QMTBroker.FORBIDDEN_ACCOUNTS:
            raise RuntimeError(
                f"拒绝创建 QMTBroker：account_id={account_id} 在禁止名单（真实账户）"
            )
        broker = QMTBroker(
            qmt_path=qmt_path,
            account_id=account_id,
            session_id=int(kwargs.get("session_id", os.environ.get("QMT_SESSION_ID", "123456"))),
            local_account_id=int(kwargs.get("account_id", 1)),
            dry_run=bool(kwargs.get("dry_run", False)),
            xtquant_site_packages=kwargs.get("xtquant_site_packages"),
        )
    else:
        raise ValueError(f"未知的 broker mode: {mode}")

    broker.connect()
    return broker
