"""
broker/qmt_broker.py — 国金 QMT 实盘 broker

⚠️ 重要前提：
1. 必须先启动 QMT 客户端并登录，否则 connect 一定失败
2. 必须安装 xtquant（QMT 自带，参考 docs/qmt_integration.md §5）
3. 测试账号 90072426 → 跑通后再切换实盘
4. 本文件目前未在真实 QMT 环境跑过，等 Phase A 装完客户端后做联调测试

设计要点（与 SimBroker 的差异）：
- 下单是异步的：buy/sell 调用 order_stock 后立刻返回 OrderResult(success=True, order_id=xxx)
  真正的成交结果走 on_stock_trade 回调，回调里把成交写到 sim_trades 表（broker='qmt'）
- 这意味着 buy/sell 返回时 amount/commission/tax 都是占位（实际值要等回调）
- 持仓/资金通过 query_stock_positions / query_stock_asset 实时查 QMT，不依赖本地账本

参考资料：docs/qmt_integration.md
"""

import logging
from datetime import date as Date, datetime
from threading import Lock
from typing import Optional

from sim.db import get_conn
from .base import IBroker, OrderResult, OrderSide, Account, Position

logger = logging.getLogger(__name__)


class QMTBroker(IBroker):
    name = "qmt"

    # ⚠️ 硬隔离：禁止连接真实账户
    FORBIDDEN_ACCOUNTS = {"8890461376"}

    def __init__(self,
                 qmt_path: str,
                 account_id: str,
                 session_id: int = 123456,
                 local_account_id: int = 1,
                 dry_run: bool = False,
                 xtquant_site_packages: str | None = None):
        """
        :param qmt_path: QMT userdata_mini 路径，例如 D:\\国金QMT\\userdata_mini
        :param account_id: 资金账号（券商账号字符串）
        :param session_id: xtquant 会话 ID，建议自定义随机数避免冲突
        :param local_account_id: 本地 sim_account 表的账户 id（用于写交易流水）
        :param dry_run: 为 True 时 buy/sell **不真调 order_stock**，只记录一条 fake OrderResult
                        用于 5/20 可控试跑 + 5/21 之前的验证
        :param xtquant_site_packages: QMT bin.x64/Lib/site-packages 路径
                        主项目 venv 没装 xtquant 时，connect 前会把它加到 sys.path
        """
        if str(account_id) in self.FORBIDDEN_ACCOUNTS:
            raise RuntimeError(
                f"⚠️ 拒绝初始化 QMTBroker：account_id={account_id} 位于禁止名单（真实账户）"
            )

        self.qmt_path = qmt_path
        self.account_id_str = account_id
        self.session_id = session_id
        self.local_account_id = local_account_id
        self.dry_run = bool(dry_run)
        self.xtquant_site_packages = xtquant_site_packages

        self._trader = None
        self._account = None
        self._connected = False

        # 委托号 -> 信号备注（下单时存，回调成交时取出写入 sim_trades）
        self._order_meta: dict[str, dict] = {}
        self._meta_lock = Lock()

        # dry-run 伪委托号计数
        self._fake_order_seq = 0

    # ---------- 内部工具 ----------
    def _ensure_xtquant(self):
        # 主项目 venv 可能没装 xtquant，先用 sys.path 补上 QMT 自带 site-packages
        import sys, os
        if self.xtquant_site_packages and os.path.isdir(self.xtquant_site_packages):
            if self.xtquant_site_packages not in sys.path:
                sys.path.insert(0, self.xtquant_site_packages)
                logger.info(f"sys.path 已增加 xtquant 路径: {self.xtquant_site_packages}")
        try:
            from xtquant import xttrader, xttype, xtconstant  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                f"未安装 xtquant。可试：\n"
                f"  1. 启动 QMT 客户端并验证 path={self.xtquant_site_packages}\n"
                f"  2. 或从 bin.x64/Lib/site-packages/xtquant 复制到主项目 venv\n"
                f"原因: {e}"
            ) from e

    def _ensure_connected(self):
        if not self._connected:
            raise RuntimeError("QMTBroker 未连接，请先调用 connect()")
        if self.dry_run:
            return  # dry-run 下 _trader / _account 始终为 None，正常现象
        if self._trader is None or self._account is None:
            raise RuntimeError("QMTBroker 未连接（_trader/_account 为空）")

    # ---------- 生命周期 ----------
    def connect(self) -> bool:
        if self.dry_run:
            logger.warning(
                f"🔶 QMTBroker dry_run=true: 跳过真实 xtquant connect，账号={self.account_id_str}"
            )
            self._connected = True
            return True

        self._ensure_xtquant()
        from xtquant.xttrader import XtQuantTrader
        from xtquant.xttype import StockAccount

        self._trader = XtQuantTrader(self.qmt_path, self.session_id)
        # 注册回调（必须先注册再 start）
        self._trader.register_callback(_QMTCallback(self))
        self._trader.start()

        ret = self._trader.connect()
        if ret != 0:
            raise RuntimeError(
                f"QMT connect 失败 code={ret}（常见原因：QMT 客户端未启动 / "
                f"userdata_mini 路径错误 / session_id 冲突）"
            )

        self._account = StockAccount(self.account_id_str)
        sub = self._trader.subscribe(self._account)
        if sub != 0:
            raise RuntimeError(f"QMT subscribe 失败 code={sub}")

        self._connected = True
        logger.info(f"QMTBroker connected: account={self.account_id_str}")
        return True

    def disconnect(self):
        if self.dry_run:
            self._connected = False
            return
        if self._trader:
            try:
                self._trader.stop()
            except Exception as e:
                logger.warning(f"QMT stop 异常: {e}")
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # ---------- 下单 ----------
    def _place_order(self, side: OrderSide, stock_code: str, price: float,
                     quantity: int, stock_name: str, signal_reason: str,
                     trade_date: Optional[Date]) -> OrderResult:
        self._ensure_connected()

        # ---- DRY-RUN 分支 ----
        if self.dry_run:
            self._fake_order_seq += 1
            fake_id = f"DRY{datetime.now().strftime('%H%M%S')}{self._fake_order_seq:03d}"
            amount = price * quantity
            commission = max(amount * 0.0003, 5.0)
            tax = amount * 0.001 if side == OrderSide.SELL else 0.0
            logger.warning(
                f"[DRY-RUN] {side.value} {stock_code} {quantity}@{price:.2f} "
                f"amount={amount:.2f} reason='{signal_reason}'"
            )
            print(
                f"[DRY-RUN] {side.value:>4} {stock_code} {quantity:>4}@{price:>7.2f}  "
                f"amount={amount:>10.2f}  fake_id={fake_id}  reason={signal_reason}",
                flush=True,
            )
            return OrderResult(
                success=True, msg="dry-run 伪委托（未真下单）",
                order_id=fake_id, stock_code=stock_code, side=side,
                price=price, quantity=quantity,
                amount=amount, commission=commission, tax=tax,
                extra={"dry_run": True, "submitted": False, "filled": False},
            )

        from xtquant import xtconstant

        if quantity % 100 != 0:
            return OrderResult(
                success=False,
                msg=f"数量必须是 100 整数倍，收到 {quantity}",
                stock_code=stock_code, side=side, price=price, quantity=quantity,
            )

        order_type = xtconstant.STOCK_BUY if side == OrderSide.BUY else xtconstant.STOCK_SELL

        try:
            order_id = self._trader.order_stock(
                account=self._account,
                stock_code=stock_code,
                order_type=order_type,
                order_volume=quantity,
                price_type=xtconstant.FIX_PRICE,
                price=price,
                strategy_name="quant-learn",
                order_remark=(signal_reason or "")[:50],
            )
        except Exception as e:
            logger.exception(f"QMT 下单异常: {side} {stock_code} {quantity}@{price}")
            return OrderResult(
                success=False, msg=f"下单异常: {e}",
                stock_code=stock_code, side=side, price=price, quantity=quantity,
            )

        # order_stock 返回值小于 0 表示失败
        if order_id is None or (isinstance(order_id, int) and order_id < 0):
            return OrderResult(
                success=False, msg=f"QMT 拒单 code={order_id}",
                stock_code=stock_code, side=side, price=price, quantity=quantity,
            )

        order_id_str = str(order_id)
        # 暂存元数据，回调里用得上
        with self._meta_lock:
            self._order_meta[order_id_str] = {
                "side": side,
                "stock_code": stock_code,
                "stock_name": stock_name,
                "signal_reason": signal_reason,
                "submit_price": price,
                "submit_quantity": quantity,
                "trade_date": trade_date,
                "submit_at": datetime.now(),
            }

        logger.info(f"QMT 已委托: id={order_id_str} {side} {stock_code} {quantity}@{price}")
        return OrderResult(
            success=True,
            msg="已委托（等待成交回调）",
            order_id=order_id_str,
            stock_code=stock_code,
            side=side,
            price=price,
            quantity=quantity,
            amount=price * quantity,           # 占位估算，真实成交以回调为准
            commission=0.0,
            tax=0.0,
            extra={"submitted": True, "filled": False},
        )

    def buy(self, stock_code: str, price: float, quantity: int,
            stock_name: str = "", signal_reason: str = "",
            trade_date: Optional[Date] = None) -> OrderResult:
        return self._place_order(OrderSide.BUY, stock_code, price, quantity,
                                 stock_name, signal_reason, trade_date)

    def sell(self, stock_code: str, price: float, quantity: int,
             stock_name: str = "", signal_reason: str = "",
             trade_date: Optional[Date] = None) -> OrderResult:
        return self._place_order(OrderSide.SELL, stock_code, price, quantity,
                                 stock_name, signal_reason, trade_date)

    def cancel(self, order_id: str) -> OrderResult:
        self._ensure_connected()
        try:
            ret = self._trader.cancel_order_stock(self._account, int(order_id))
        except Exception as e:
            return OrderResult(success=False, msg=f"撤单异常: {e}", order_id=order_id)
        if ret != 0:
            return OrderResult(success=False, msg=f"撤单失败 code={ret}", order_id=order_id)
        return OrderResult(success=True, msg="已发起撤单", order_id=order_id)

    # ---------- 查询 ----------
    def get_account(self) -> Account:
        self._ensure_connected()
        if self.dry_run:
            # dry-run 下返回一个伪账户（带上初始 1000w，与 QMT 模拟账户初始资金一致）
            return Account(
                cash=10_000_000.0, total_value=10_000_000.0, market_value=0.0,
                initial_cash=10_000_000.0,
                extra={"dry_run": True, "queried_at": datetime.now().isoformat()},
            )
        asset = self._trader.query_stock_asset(self._account)
        if asset is None:
            raise RuntimeError("QMT query_stock_asset 返回空")
        # xtquant 字段：cash / frozen_cash / market_value / total_asset
        return Account(
            cash=float(asset.cash),
            total_value=float(asset.total_asset),
            market_value=float(asset.market_value),
            initial_cash=0.0,  # QMT 不暴露初始资金，本地不维护
            extra={
                "frozen_cash": float(getattr(asset, "frozen_cash", 0)),
                "queried_at": datetime.now().isoformat(),
            },
        )

    def get_positions(self) -> list[Position]:
        self._ensure_connected()
        if self.dry_run:
            # dry-run 下始终返空仓（QMT 模拟账户 90072426 现在本身就是空仓）
            return []
        rows = self._trader.query_stock_positions(self._account) or []
        out: list[Position] = []
        for p in rows:
            qty = int(p.volume)
            if qty <= 0:
                continue
            avg_cost = float(getattr(p, "open_price", 0) or getattr(p, "avg_price", 0))
            cur_price = float(getattr(p, "last_price", 0) or 0)
            mv = float(getattr(p, "market_value", 0) or cur_price * qty)
            cost = avg_cost * qty
            pnl = mv - cost
            pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0
            out.append(Position(
                stock_code=p.stock_code,
                stock_name=getattr(p, "stock_name", "") or "",
                quantity=qty,
                avg_cost=avg_cost,
                current_price=cur_price,
                market_value=mv,
                pnl=pnl,
                pnl_pct=pnl_pct,
            ))
        return out

    def update_prices(self, price_dict: dict):
        # QMT 自己维护实时市值，不需要本地推。如需对账可在这里同步到 sim_positions
        pass

    def daily_settle(self, trade_date: Optional[Date] = None) -> dict:
        """每日结算：拉一次资金，写入 sim_account_nav 表"""
        self._ensure_connected()
        acc = self.get_account()
        td = trade_date or Date.today()

        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO sim_account_nav
                   (account_id, trade_date, cash, market_value, total_value)
                   VALUES (?, ?, ?, ?, ?)""",
                (self.local_account_id, td.isoformat(),
                 acc.cash, acc.market_value, acc.total_value),
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "success": True,
            "trade_date": td.isoformat(),
            "cash": acc.cash,
            "market_value": acc.market_value,
            "total_value": acc.total_value,
        }

    # ---------- 回调内部使用 ----------
    def _on_trade_filled(self, trade) -> None:
        """成交回调：把成交流水写入 sim_trades，broker='qmt'"""
        try:
            order_id = str(trade.order_id)
            with self._meta_lock:
                meta = self._order_meta.get(order_id, {})

            stock_code = trade.stock_code
            side = meta.get("side") or (
                OrderSide.BUY if getattr(trade, "order_type", 23) == 23 else OrderSide.SELL
            )
            price = float(trade.traded_price)
            qty = int(trade.traded_volume)
            amount = price * qty

            # 简单按 A 股标准费率计算（实际可读 trade.commission_fee 等字段）
            commission = max(amount * 0.0003, 5.0)
            tax = amount * 0.001 if side == OrderSide.SELL else 0.0

            conn = get_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO sim_trades
                       (account_id, trade_date, stock_code, stock_name, side,
                        price, quantity, amount, commission, tax,
                        signal_reason, broker, order_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        self.local_account_id,
                        (meta.get("trade_date") or Date.today()).isoformat(),
                        stock_code,
                        meta.get("stock_name") or getattr(trade, "stock_name", "") or "",
                        side.value if hasattr(side, "value") else str(side),
                        price, qty, amount, commission, tax,
                        meta.get("signal_reason", ""),
                        "qmt",
                        order_id,
                        datetime.now().isoformat(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            logger.info(f"QMT 成交落库: {side} {stock_code} {qty}@{price} order={order_id}")
        except Exception:
            logger.exception("处理成交回调异常")


# ============================================================
# xtquant 回调类（必须独立类，xtquant 接口约定）
# ============================================================
class _QMTCallback:
    """xtquant XtQuantTraderCallback 的实现。
    定义为普通类、按需 import 父类，避免顶层 import 失败。
    """

    def __init__(self, broker: QMTBroker):
        self.broker = broker
        # 让回调对象同时是 XtQuantTraderCallback 子类（晚绑定）
        try:
            from xtquant.xttrader import XtQuantTraderCallback
            # 动态把 XtQuantTraderCallback 加到 _QMTCallback 的基类列表里
            self.__class__.__bases__ = (XtQuantTraderCallback,) + tuple(
                b for b in self.__class__.__bases__ if b is not object
            )
        except Exception as e:
            logger.warning(f"无法绑定 XtQuantTraderCallback: {e}")

    def on_stock_order(self, order):
        logger.info(
            f"[QMT] 委托状态: id={getattr(order, 'order_id', '')} "
            f"status={getattr(order, 'order_status', '')} "
            f"code={getattr(order, 'stock_code', '')}"
        )

    def on_stock_trade(self, trade):
        logger.info(
            f"[QMT] 成交: id={trade.order_id} {trade.stock_code} "
            f"{trade.traded_volume}@{trade.traded_price}"
        )
        self.broker._on_trade_filled(trade)

    def on_order_error(self, err):
        logger.error(
            f"[QMT] 委托失败: id={getattr(err, 'order_id', '')} "
            f"err={getattr(err, 'error_msg', err)}"
        )

    def on_cancel_error(self, err):
        logger.error(f"[QMT] 撤单失败: {getattr(err, 'error_msg', err)}")

    def on_disconnected(self):
        logger.warning("[QMT] 连接已断开，请检查 QMT 客户端")
        self.broker._connected = False

    def on_connected(self):
        logger.info("[QMT] 连接已建立")
