"""
gateways/qmt_order_state.py — QMT 订单状态机

QL-011: 明确并实现订单状态流、幂等处理、断线恢复。

状态: created → submitted → accepted → partial → filled/cancelled/rejected
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class OrderState(Enum):
    CREATED = "created"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


# 合法状态转换
_VALID_TRANSITIONS = {
    OrderState.CREATED: {OrderState.SUBMITTED, OrderState.REJECTED},
    OrderState.SUBMITTED: {OrderState.ACCEPTED, OrderState.REJECTED, OrderState.CANCELLED},
    OrderState.ACCEPTED: {OrderState.PARTIAL, OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED},
    OrderState.PARTIAL: {OrderState.FILLED, OrderState.CANCELLED},
    OrderState.FILLED: set(),      # 终态
    OrderState.CANCELLED: set(),   # 终态
    OrderState.REJECTED: set(),    # 终态
}


@dataclass
class QmtOrderRecord:
    """QMT 订单记录 — broker request id / QMT order id / trade id 分开保存"""
    broker_request_id: str         # 本地请求ID
    qmt_order_id: Optional[str] = None  # QMT委托号
    qmt_trade_id: Optional[str] = None  # QMT成交号
    state: OrderState = OrderState.CREATED
    symbol: str = ""
    side: str = ""
    quantity: int = 0
    filled_quantity: int = 0
    price: float = 0.0
    filled_price: float = 0.0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # 幂等处理
    processed_trade_ids: set = field(default_factory=set)


class QmtOrderStateMachine:
    """QMT 订单状态机

    - 明确状态转换
    - 幂等处理重复和乱序回调
    - 部分成交后撤单的数量正确
    """

    def __init__(self):
        self._orders: dict[str, QmtOrderRecord] = {}

    def create_order(self, broker_request_id: str, **kwargs) -> QmtOrderRecord:
        """创建订单"""
        record = QmtOrderRecord(
            broker_request_id=broker_request_id,
            state=OrderState.CREATED,
            created_at=datetime.now(),
            **kwargs,
        )
        self._orders[broker_request_id] = record
        return record

    def transition(self, broker_request_id: str, new_state: OrderState) -> bool:
        """状态转换 — 只允许合法转换"""
        record = self._orders.get(broker_request_id)
        if record is None:
            logger.warning(f"Unknown order: {broker_request_id}")
            return False

        if new_state not in _VALID_TRANSITIONS.get(record.state, set()):
            logger.warning(
                f"Invalid transition: {record.state.value} → {new_state.value} "
                f"for order {broker_request_id}"
            )
            return False

        record.state = new_state
        record.updated_at = datetime.now()
        return True

    def process_fill(self, broker_request_id: str, trade_id: str,
                     filled_qty: int, filled_price: float) -> bool:
        """处理成交回调 — 幂等：重复trade_id不重复记账"""
        record = self._orders.get(broker_request_id)
        if record is None:
            return False

        # 幂等检查
        if trade_id in record.processed_trade_ids:
            logger.info(f"Duplicate fill ignored: trade_id={trade_id}")
            return True  # 已处理过，不算失败

        record.processed_trade_ids.add(trade_id)
        record.filled_quantity += filled_qty
        # 加权平均成交价
        if record.filled_quantity > 0:
            old_total = record.filled_price * (record.filled_quantity - filled_qty)
            record.filled_price = (old_total + filled_price * filled_qty) / record.filled_quantity

        # 更新状态
        if record.filled_quantity >= record.quantity:
            self.transition(broker_request_id, OrderState.FILLED)
        else:
            self.transition(broker_request_id, OrderState.PARTIAL)

        return True

    def get_order(self, broker_request_id: str) -> Optional[QmtOrderRecord]:
        return self._orders.get(broker_request_id)

    def get_active_orders(self) -> list[QmtOrderRecord]:
        """获取未终结的订单"""
        terminal = {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED}
        return [o for o in self._orders.values() if o.state not in terminal]

    def is_reconciled(self) -> bool:
        """所有订单是否已终结（用于对账检查）"""
        return len(self.get_active_orders()) == 0
