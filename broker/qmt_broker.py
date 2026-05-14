"""
broker/qmt_broker.py — 国金 QMT 实盘 broker（占位实现）

⚠️ 此文件目前仅为骨架，等 QMT 客户端 + xtquant 安装好后再补具体实现。

真正实现思路：
1. connect: 创建 XtQuantTrader 实例，注册回调，连接到 QMT 主进程
2. buy/sell: 调用 trader.order_stock(account, code, order_type, qty, price, ...)
3. 回调里把成交事件写入本地 sim_trades 表（broker='qmt'），保持账本一致
4. 撤单/查询持仓/资金都走 xtquant 同名 API

参考资料：
- xtquant 官方文档：QMT 安装目录下的 doc/ 文件夹
- 本项目对接 spec：docs/qmt_integration.md（待补）
"""

from datetime import date as Date
from typing import Optional

from .base import IBroker, OrderResult, OrderSide, Account, Position


class QMTBroker(IBroker):
    name = "qmt"

    def __init__(self,
                 qmt_path: str,
                 account_id: str,
                 session_id: int = 123456,
                 local_account_id: int = 1):
        """
        :param qmt_path: QMT userdata_mini 路径，例如 D:\\国金QMT\\userdata_mini
        :param account_id: 资金账号（券商账号字符串）
        :param session_id: xtquant 会话 ID，建议自定义随机数避免冲突
        :param local_account_id: 本地 sim_account 表的账户 id（用于写交易流水）
        """
        self.qmt_path = qmt_path
        self.account_id_str = account_id
        self.session_id = session_id
        self.local_account_id = local_account_id

        self._trader = None
        self._account = None
        self._connected = False

    def _ensure_xtquant(self):
        try:
            from xtquant import xttrader, xttype  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "未安装 xtquant。请从 QMT 客户端安装目录复制 xtquant 文件夹到 Python site-packages，"
                "或参考 docs/qmt_integration.md。"
            ) from e

    def connect(self) -> bool:
        self._ensure_xtquant()
        from xtquant.xttrader import XtQuantTrader
        from xtquant.xttype import StockAccount

        self._trader = XtQuantTrader(self.qmt_path, self.session_id)
        self._trader.start()
        ok = self._trader.connect()
        if ok != 0:
            raise RuntimeError(f"QMT connect 失败 code={ok}")
        self._account = StockAccount(self.account_id_str)
        sub = self._trader.subscribe(self._account)
        if sub != 0:
            raise RuntimeError(f"QMT subscribe 失败 code={sub}")
        self._connected = True
        return True

    def disconnect(self):
        if self._trader:
            try:
                self._trader.stop()
            except Exception:
                pass
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # ---------- 下单（占位） ----------
    def buy(self, stock_code: str, price: float, quantity: int,
            stock_name: str = "", signal_reason: str = "",
            trade_date: Optional[Date] = None) -> OrderResult:
        raise NotImplementedError("QMTBroker.buy 待实现，等 QMT 装好后补")

    def sell(self, stock_code: str, price: float, quantity: int,
             stock_name: str = "", signal_reason: str = "",
             trade_date: Optional[Date] = None) -> OrderResult:
        raise NotImplementedError("QMTBroker.sell 待实现，等 QMT 装好后补")

    def cancel(self, order_id: str) -> OrderResult:
        raise NotImplementedError("QMTBroker.cancel 待实现")

    def get_account(self) -> Account:
        raise NotImplementedError("QMTBroker.get_account 待实现")

    def get_positions(self) -> list[Position]:
        raise NotImplementedError("QMTBroker.get_positions 待实现")

    def update_prices(self, price_dict: dict):
        # 实盘的市值由 QMT 自己维护，这里可以选择性同步到本地 sim_positions 做对账
        pass

    def daily_settle(self, trade_date: Optional[Date] = None) -> dict:
        raise NotImplementedError("QMTBroker.daily_settle 待实现")
