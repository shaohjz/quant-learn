"""
broker/sim_broker.py — 模拟盘 broker

完全本地撮合，复用 sim/engine 的 SimEngine 做账本管理。
所有买卖立即成交在传入的 price，没有滑点（如需可后续加 slippage 参数）。
"""

from datetime import date as Date
from typing import Optional

from sim.engine import SimEngine
from .base import IBroker, OrderResult, OrderSide, Account, Position


class SimBroker(IBroker):
    name = "sim"

    def __init__(self, account_id: int = 1, slippage: float = 0.0):
        """
        :param slippage: 撮合滑点，0 表示按传入价成交；
                         例如 0.001 表示买价 +0.1%，卖价 -0.1%
        """
        self.account_id = account_id
        self.slippage = slippage
        self.engine = SimEngine(account_id=account_id)
        self._connected = False

    # ---------- 生命周期 ----------
    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self):
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # ---------- 下单 ----------
    def buy(self, stock_code: str, price: float, quantity: int,
            stock_name: str = "", signal_reason: str = "",
            trade_date: Optional[Date] = None,
            signal_detail: dict = None) -> OrderResult:
        exec_price = price * (1 + self.slippage) if self.slippage else price
        r = self.engine.buy(
            stock_code=stock_code, price=exec_price, quantity=quantity,
            stock_name=stock_name, signal_reason=signal_reason,
            trade_date=trade_date, broker=self.name,
            signal_detail=signal_detail,
        )
        return OrderResult(
            success=r.get("success", False),
            msg=r.get("msg", ""),
            order_id=None,
            stock_code=stock_code,
            side=OrderSide.BUY,
            price=exec_price,
            quantity=quantity,
            amount=r.get("amount", 0),
            commission=r.get("commission", 0),
        )

    def sell(self, stock_code: str, price: float, quantity: int,
             stock_name: str = "", signal_reason: str = "",
             trade_date: Optional[Date] = None,
             signal_detail: dict = None) -> OrderResult:
        exec_price = price * (1 - self.slippage) if self.slippage else price
        r = self.engine.sell(
            stock_code=stock_code, price=exec_price, quantity=quantity,
            stock_name=stock_name, signal_reason=signal_reason,
            trade_date=trade_date, broker=self.name,
            signal_detail=signal_detail,
        )
        return OrderResult(
            success=r.get("success", False),
            msg=r.get("msg", ""),
            stock_code=stock_code,
            side=OrderSide.SELL,
            price=exec_price,
            quantity=quantity,
            amount=r.get("amount", 0),
            commission=r.get("commission", 0),
            tax=r.get("tax", 0),
        )

    def cancel(self, order_id: str) -> OrderResult:
        # 模拟盘是立即成交的，没有未完成订单可撤
        return OrderResult(success=False, msg="SimBroker 立即成交，不支持撤单",
                           order_id=order_id)

    # ---------- 查询 ----------
    def get_account(self) -> Account:
        a = self.engine.get_account()
        positions = self.engine.get_positions()
        market_value = sum(float(p["market_value"] or 0) for p in positions)
        return Account(
            cash=a["cash"],
            total_value=a["total_value"],
            market_value=market_value,
            initial_cash=a["initial_cash"],
            extra={"updated_at": str(a.get("updated_at", ""))},
        )

    def get_positions(self) -> list[Position]:
        rows = self.engine.get_positions()
        out = []
        for r in rows:
            out.append(Position(
                stock_code=r["stock_code"],
                stock_name=r["stock_name"] or "",
                quantity=int(r["quantity"]),
                avg_cost=float(r["avg_cost"] or 0),
                current_price=float(r["current_price"] or 0),
                market_value=float(r["market_value"] or 0),
                pnl=float(r["pnl"] or 0),
                pnl_pct=float(r["pnl_pct"] or 0),
            ))
        return out

    # ---------- 账本辅助 ----------
    def update_prices(self, price_dict: dict):
        self.engine.update_prices(price_dict)

    def daily_settle(self, trade_date: Optional[Date] = None) -> dict:
        return self.engine.daily_settle(trade_date)
