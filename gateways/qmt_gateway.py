"""gateways/qmt_gateway.py — 轻量 vnpy QMT Gateway（基于 xtquant 直连）

为什么自己写？
  - 官方 `vnpy_xtquant` 在 PyPI 上没有 release，git+ 安装在当前环境下无 git 二进制。
  - 项目根 `broker/qmt_broker.py` 已经验证过 xtquant 链路（mini 模拟账户 90072426 OK），
    把同一套逻辑包成 vnpy `BaseGateway` 子类即可，避免引入未审过的第三方仓库。

实现范围（够用即可，不追求完整 vnpy 协议）：
  - connect()       —— 启动 xtquant.xttrader，订阅 xtdata 行情
  - subscribe()     —— 把 vnpy SubscribeRequest 转成 xtdata.subscribe_quote
  - send_order()    —— 走 xttrader.order_stock_async，dry_run 时只打 log
  - cancel_order()  —— 走 xttrader.cancel_order_stock_async
  - query_account() —— 同步查 query_stock_asset
  - query_position()—— 同步查 query_stock_positions

⚠️ 风控：
  - FORBIDDEN_ACCOUNTS 与 broker/qmt_broker.py 保持一致（永远禁连真实账号 8890461376）
  - 默认 dry_run=True，必须显式 dry_run=False 才会真发单
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from vnpy.event import EventEngine
from vnpy.trader.constant import (
    Direction,
    Exchange,
    OrderType,
    Product,
    Status,
)
from vnpy.trader.gateway import BaseGateway
from vnpy.trader.object import (
    AccountData,
    CancelRequest,
    ContractData,
    OrderData,
    OrderRequest,
    PositionData,
    SubscribeRequest,
    TickData,
    TradeData,
)

logger = logging.getLogger(__name__)

# 与 broker/qmt_broker.py 同步硬隔离
FORBIDDEN_ACCOUNTS = {"8890461376"}

# xtquant 仅支持 Python <= 3.11（二进制 .pyd 编译版本上限 cp311）
# 如果当前 Python >= 3.12，QMT 网关功能自动禁用，避免 ImportError
QMT_PYTHON_MAX = (3, 12)
VENV_QMT_PATH = Path(__file__).resolve().parent.parent / "venv_qmt" / "Scripts" / "python.exe"


def _check_qmt_python_compat() -> bool:
    """检查当前 Python 版本是否兼容 xtquant。

    Returns:
        True  = 兼容（<= 3.11），可以正常加载 xtquant
        False = 不兼容（>= 3.12），QMT 网关功能将被禁用
    """
    if sys.version_info >= QMT_PYTHON_MAX:
        logger.warning(
            f"QMT xtquant 需要 Python <= 3.11，当前版本为 {sys.version_info.major}.{sys.version_info.minor}"
        )
        logger.warning(
            f"QMT 网关功能已自动禁用。如需使用，请通过 venv_qmt 运行：\n"
            f"  {VENV_QMT_PATH} -m gateways.qmt_gateway\n"
            f"或设置 QMT_USE_VENV=1 自动切换到 venv"
        )
        return False
    return True


# 模块加载时即检查兼容性，设置 QMT_AVAILABLE 标志
QMT_AVAILABLE = _check_qmt_python_compat()


def _stockcode_to_xt(symbol: str, exchange: Exchange) -> str:
    """vnpy symbol+exchange → xtquant 形式 '600330.SH'"""
    suffix = "SH" if exchange == Exchange.SSE else "SZ"
    return f"{symbol}.{suffix}"


def _xt_to_vnpy(xt_code: str) -> tuple[str, Exchange]:
    """xtquant '600330.SH' → ('600330', Exchange.SSE)"""
    sym, suf = xt_code.split(".")
    return sym, (Exchange.SSE if suf.upper() == "SH" else Exchange.SZSE)


def _guess_exchange(symbol: str) -> Exchange:
    """A 股按代码首位推断（与 sim/realtime_price 等老逻辑一致）"""
    if symbol.startswith(("60", "68", "9")):
        return Exchange.SSE
    return Exchange.SZSE


class QmtGateway(BaseGateway):
    """vnpy 风格的 QMT mini gateway。

    settings 必填字段：
      - qmt_path: QMT userdata_mini 绝对路径
      - qmt_account: 资金账号字符串
      - session_id: xtquant 会话 id（自定义随机数即可）
      - xtquant_site_packages: QMT 自带 xtquant 的 site-packages 路径
      - dry_run: True 时不真下单（默认 True，安全起见）
    """

    default_name: str = "QMT"
    exchanges = [Exchange.SSE, Exchange.SZSE]
    default_setting = {
        "qmt_path": "",
        "qmt_account": "",
        "session_id": 970525,
        "xtquant_site_packages": "",
        "dry_run": True,
    }

    def __init__(self, event_engine: EventEngine, gateway_name: str = "QMT"):
        super().__init__(event_engine, gateway_name)
        self.qmt_path: str = ""
        self.account_id: str = ""
        self.session_id: int = 0
        self.dry_run: bool = True

        self._xt_trader = None
        self._xt_account = None
        self._xtdata = None
        self._xttrader_mod = None
        self._xttype = None

        # 模拟订单号（dry_run 模式下用）
        self._fake_order_seq = 0
        # vnpy_orderid -> xt order_id（真实模式）
        self._orderid_map: dict[str, str] = {}
        # 已订阅 symbol（防重复）
        self._subscribed: set[str] = set()

    # ============================================================
    # 连接
    # ============================================================
    def connect(self, setting: dict) -> None:
        if not QMT_AVAILABLE:
            self.write_log(
                "❌ QMT 网关不可用：当前 Python 版本不兼容 xtquant "
                "(需要 Python <= 3.11)。\n"
                "解决方案：\n"
                f"  1. 使用 venv_qmt: {VENV_QMT_PATH} -m gateways.qmt_gateway\n"
                f"  2. 或设置环境变量 QMT_USE_VENV=1 自动切换"
            )
            raise RuntimeError("QMT xtquant incompatible Python version")

        self.qmt_path = setting["qmt_path"]
        self.account_id = str(setting["qmt_account"])
        self.session_id = int(setting.get("session_id", 970525))
        self.dry_run = bool(setting.get("dry_run", True))
        xt_site = setting.get("xtquant_site_packages", "")

        if self.account_id in FORBIDDEN_ACCOUNTS:
            self.write_log(f"⛔ 拒绝连接禁止账户: {self.account_id}")
            raise RuntimeError(f"forbidden account: {self.account_id}")

        # 把 xtquant site-packages 加到 sys.path
        if xt_site and Path(xt_site).is_dir() and xt_site not in sys.path:
            sys.path.insert(0, xt_site)

        try:
            from xtquant import xtdata, xttrader  # type: ignore
            from xtquant import xttype  # type: ignore
        except Exception as e:  # noqa: BLE001
            self.write_log(f"❌ xtquant import 失败: {e}")
            raise

        self._xtdata = xtdata
        self._xttrader_mod = xttrader
        self._xttype = xttype

        # 创建 trader（dry_run 时也连一下，但不下单）
        try:
            self._xt_trader = xttrader.XtQuantTrader(self.qmt_path, self.session_id)
            self._xt_account = xttype.StockAccount(self.account_id)
            self._xt_trader.start()
            connect_ret = self._xt_trader.connect()
            if connect_ret != 0:
                self.write_log(f"⚠️ XtQuantTrader.connect 返回 {connect_ret}（QMT 客户端未启动？）")
            sub_ret = self._xt_trader.subscribe(self._xt_account)
            if sub_ret != 0:
                self.write_log(f"⚠️ subscribe 账户返回 {sub_ret}")
            self.write_log(
                f"✅ QMT trader 连接成功 acct={self.account_id} session={self.session_id} dry_run={self.dry_run}"
            )
        except Exception as e:  # noqa: BLE001
            self.write_log(f"❌ XtQuantTrader 启动失败: {e}（如果只想跑行情可忽略）")

        # 立即查一次资金/持仓推到事件总线
        try:
            self.query_account()
            self.query_position()
        except Exception as e:  # noqa: BLE001
            self.write_log(f"⚠️ 初次查询资金/持仓失败: {e}")

        # 注册常用汇台合约（让 vnpy CtaEngine 能 subscribe）
        # 包括持仓 5 只 + 观察池 5 只，如需动态添加可调 push_contracts()
        try:
            default_codes = [
                "600330", "002256", "002453", "002342", "603601",
                "002709", "002149", "002156", "605006", "603757",
            ]
            self.push_contracts(default_codes)
        except Exception as e:  # noqa: BLE001
            self.write_log(f"⚠️ push_contracts 失败: {e}")

    def push_contracts(self, codes: list[str]) -> None:
        """批量推送 ContractData，让 vnpy CtaEngine subscribe 能找到合约。"""
        for code in codes:
            ex = _guess_exchange(code)
            contract = ContractData(
                gateway_name=self.gateway_name,
                symbol=code,
                exchange=ex,
                name=code,
                product=Product.EQUITY,
                size=1,
                pricetick=0.01,
                min_volume=100,
                history_data=False,
            )
            self.on_contract(contract)

    def close(self) -> None:
        try:
            if self._xt_trader is not None:
                self._xt_trader.stop()
                self.write_log("QMT trader stopped")
        except Exception:  # noqa: BLE001
            pass

    # ============================================================
    # 行情
    # ============================================================
    def subscribe(self, req: SubscribeRequest) -> None:
        if self._xtdata is None:
            self.write_log("⚠️ xtdata 尚未初始化，无法订阅")
            return
        xt_code = _stockcode_to_xt(req.symbol, req.exchange)
        if xt_code in self._subscribed:
            return
        self._subscribed.add(xt_code)

        def _on_quote(datas: dict):
            try:
                for code, kline in datas.items():
                    # kline 通常是 list[dict]
                    if not kline:
                        continue
                    rec = kline[-1] if isinstance(kline, list) else kline
                    last = float(rec.get("lastPrice") or rec.get("close") or 0)
                    if last <= 0:
                        continue
                    sym, ex = _xt_to_vnpy(code)
                    tick = TickData(
                        gateway_name=self.gateway_name,
                        symbol=sym,
                        exchange=ex,
                        datetime=datetime.now(),
                        last_price=last,
                        volume=float(rec.get("volume") or 0),
                        open_price=float(rec.get("open") or 0),
                        high_price=float(rec.get("high") or 0),
                        low_price=float(rec.get("low") or 0),
                        pre_close=float(rec.get("lastClose") or 0),
                    )
                    self.on_tick(tick)
            except Exception as e:  # noqa: BLE001
                self.write_log(f"on_quote 处理出错: {e}")

        try:
            self._xtdata.subscribe_quote(xt_code, period="tick", count=-1, callback=_on_quote)
            self.write_log(f"📡 订阅 {xt_code}")
        except Exception as e:  # noqa: BLE001
            self.write_log(f"⚠️ 订阅 {xt_code} 失败: {e}")

    # ============================================================
    # 委托
    # ============================================================
    def send_order(self, req: OrderRequest) -> str:
        """返回 vnpy_orderid（gateway 内部唯一）"""
        self._fake_order_seq += 1
        local_id = f"{self.gateway_name}-{self._fake_order_seq:06d}"
        xt_code = _stockcode_to_xt(req.symbol, req.exchange)

        order = OrderData(
            gateway_name=self.gateway_name,
            symbol=req.symbol,
            exchange=req.exchange,
            orderid=local_id,
            type=req.type,
            direction=req.direction,
            volume=req.volume,
            price=req.price,
            status=Status.SUBMITTING,
            datetime=datetime.now(),
        )
        self.on_order(order)

        if self.dry_run:
            self.write_log(
                f"🟡 [dry_run] {req.direction.value} {xt_code} qty={int(req.volume)} px={req.price}"
            )
            order.status = Status.NOTTRADED
            self.on_order(order)
            return local_id

        if self._xt_trader is None:
            self.write_log("❌ trader 未连接，下单忽略")
            order.status = Status.REJECTED
            self.on_order(order)
            return local_id

        try:
            xt = self._xttype
            stock_buy = xt.STOCK_BUY if req.direction == Direction.LONG else xt.STOCK_SELL
            price_type = (
                xt.FIX_PRICE if req.type == OrderType.LIMIT else xt.LATEST_PRICE
            )
            xt_orderid = self._xt_trader.order_stock_async(
                self._xt_account,
                xt_code,
                stock_buy,
                int(req.volume),
                price_type,
                float(req.price),
                "vnpy",
                local_id,
            )
            self._orderid_map[local_id] = str(xt_orderid)
            self.write_log(
                f"✅ 已发单 {req.direction.value} {xt_code} qty={int(req.volume)} px={req.price} xt_id={xt_orderid}"
            )
            order.status = Status.NOTTRADED
            self.on_order(order)
        except Exception as e:  # noqa: BLE001
            self.write_log(f"❌ 下单异常: {e}")
            order.status = Status.REJECTED
            self.on_order(order)
        return local_id

    def cancel_order(self, req: CancelRequest) -> None:
        if self.dry_run or self._xt_trader is None:
            self.write_log(f"🟡 [dry_run/cancel] {req.orderid}")
            return
        xt_id = self._orderid_map.get(req.orderid)
        if not xt_id:
            self.write_log(f"⚠️ 未知委托号 {req.orderid}")
            return
        try:
            self._xt_trader.cancel_order_stock_async(self._xt_account, int(xt_id))
        except Exception as e:  # noqa: BLE001
            self.write_log(f"撤单异常: {e}")

    # ============================================================
    # 查询
    # ============================================================
    def query_account(self) -> None:
        if self._xt_trader is None or self._xt_account is None:
            return
        try:
            asset = self._xt_trader.query_stock_asset(self._xt_account)
            if asset is None:
                return
            acc = AccountData(
                gateway_name=self.gateway_name,
                accountid=self.account_id,
                balance=float(getattr(asset, "total_asset", 0) or 0),
                frozen=float(getattr(asset, "frozen_cash", 0) or 0),
            )
            self.on_account(acc)
        except Exception as e:  # noqa: BLE001
            self.write_log(f"query_account 失败: {e}")

    def query_position(self) -> None:
        if self._xt_trader is None or self._xt_account is None:
            return
        try:
            positions = self._xt_trader.query_stock_positions(self._xt_account) or []
            for p in positions:
                xt_code = getattr(p, "stock_code", "")
                if not xt_code or "." not in xt_code:
                    continue
                sym, ex = _xt_to_vnpy(xt_code)
                pos = PositionData(
                    gateway_name=self.gateway_name,
                    symbol=sym,
                    exchange=ex,
                    direction=Direction.NET,
                    volume=float(getattr(p, "volume", 0) or 0),
                    frozen=float(getattr(p, "frozen_volume", 0) or 0),
                    price=float(getattr(p, "open_price", 0) or 0),
                    pnl=float(getattr(p, "market_value", 0) or 0)
                    - float(getattr(p, "open_price", 0) or 0)
                    * float(getattr(p, "volume", 0) or 0),
                )
                self.on_position(pos)
        except Exception as e:  # noqa: BLE001
            self.write_log(f"query_position 失败: {e}")

    def query_history(self, req):
        # 历史 K 线：交给回测引擎自己用 xtdata.get_market_data，这里不实现
        return []
