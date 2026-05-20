"""
vqlearn/gateways/akshare_gateway.py — 用 akshare 做行情数据源的 vnpy Gateway

仿 vnpy Gateway 接口，但只实现行情订阅（不实现交易，交易交给 PaperAccount）。

订阅模式：轮询（A 股没有真正的免费 tick 推送）
- 默认 5 秒轮询一次 spot
- 把价格变化推送成 vnpy TickData 事件
- 引擎里其它策略订阅 EVENT_TICK 即可拿到
"""
from __future__ import annotations

import threading
import time
import logging
from datetime import datetime
from typing import Set

from vnpy.event import EventEngine, Event
from vnpy.trader.gateway import BaseGateway
from vnpy.trader.object import (
    SubscribeRequest, OrderRequest, CancelRequest,
    TickData, ContractData, HistoryRequest, BarData,
    QuoteData, QuoteRequest,
)
from vnpy.trader.constant import Exchange, Product, Interval

logger = logging.getLogger(__name__)


def _norm_to_vt(code: str) -> tuple[str, Exchange]:
    """002256 → (002256, SZSE); 600330 → (600330, SSE)"""
    code = code.split(".")[0]
    if code.startswith(("60", "68", "11", "12", "5")):
        return code, Exchange.SSE
    if code.startswith(("00", "30", "15", "16")):
        return code, Exchange.SZSE
    if code.startswith(("83", "87", "92", "43")):
        return code, Exchange.BSE
    return code, Exchange.SSE


def _ak_code(code: str) -> str:
    """vt 内部统一存 6 位代码（akshare 用纯数字代码）"""
    return code.split(".")[0]


class AkshareGateway(BaseGateway):
    """akshare 数据源 Gateway（行情 only）"""

    default_name: str = "AKSHARE"
    default_setting: dict = {
        "轮询间隔(秒)": 5,
    }
    exchanges: list = [Exchange.SSE, Exchange.SZSE, Exchange.BSE]

    def __init__(self, event_engine: EventEngine, gateway_name: str = "AKSHARE") -> None:
        super().__init__(event_engine, gateway_name)
        self.subscribed: Set[str] = set()
        self.poll_interval: float = 5.0
        self._poll_thread: threading.Thread | None = None
        self._stop_flag = threading.Event()

    # ----- vnpy 标准接口 -----
    def connect(self, setting: dict) -> None:
        self.poll_interval = float(setting.get("轮询间隔(秒)", 5))
        self.write_log(f"akshare gateway 启动（行情 only），轮询 {self.poll_interval}s")
        self._stop_flag.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, name="akshare-poll", daemon=True)
        self._poll_thread.start()

    def close(self) -> None:
        self._stop_flag.set()
        self.write_log("akshare gateway 已关闭")

    def subscribe(self, req: SubscribeRequest) -> None:
        symbol = req.symbol
        self.subscribed.add(symbol)
        self.write_log(f"订阅 {symbol}.{req.exchange.value} (累计 {len(self.subscribed)} 只)")

        # 推送一个合约元数据
        contract = ContractData(
            gateway_name=self.gateway_name,
            symbol=symbol,
            exchange=req.exchange,
            name=symbol,
            product=Product.EQUITY,
            size=1,
            pricetick=0.01,
        )
        self.on_contract(contract)

    def send_order(self, req: OrderRequest) -> str:
        # 不接收交易，交易由 PaperAccount 处理
        self.write_log(f"akshare gateway 不支持下单，转给 PaperAccount: {req.symbol}")
        return ""

    def cancel_order(self, req: CancelRequest) -> None:
        pass

    def query_account(self) -> None:
        pass

    def query_position(self) -> None:
        pass

    def send_quote(self, req: QuoteRequest) -> str:
        return ""

    def cancel_quote(self, req: CancelRequest) -> None:
        pass

    def query_history(self, req: HistoryRequest) -> list[BarData]:
        """拉取历史 K 线（akshare）"""
        import akshare as ak

        symbol = _ak_code(req.symbol)
        start = req.start.strftime("%Y%m%d") if req.start else ""
        end = req.end.strftime("%Y%m%d") if req.end else ""
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol, period="daily", adjust="qfq",
                start_date=start, end_date=end,
            )
        except Exception as e:
            self.write_log(f"history {symbol} 失败: {e}")
            return []

        if df is None or len(df) == 0:
            return []

        bars: list[BarData] = []
        for _, row in df.iterrows():
            try:
                dt = datetime.strptime(str(row["日期"]), "%Y-%m-%d")
                bar = BarData(
                    gateway_name=self.gateway_name,
                    symbol=req.symbol,
                    exchange=req.exchange,
                    datetime=dt,
                    interval=Interval.DAILY,
                    volume=float(row.get("成交量", 0)),
                    turnover=float(row.get("成交额", 0)),
                    open_price=float(row["开盘"]),
                    high_price=float(row["最高"]),
                    low_price=float(row["最低"]),
                    close_price=float(row["收盘"]),
                )
                bars.append(bar)
            except Exception:
                continue
        return bars

    # ----- 内部轮询 -----
    def _poll_loop(self) -> None:
        first = True
        while not self._stop_flag.is_set():
            if not self.subscribed:
                time.sleep(self.poll_interval if not first else 1)
                continue
            try:
                self._poll_once()
            except Exception as e:
                logger.exception(f"轮询失败: {e}")
            first = False
            time.sleep(self.poll_interval)

    def _poll_once(self) -> None:
        # 用现有 sim/realtime_price 模块（新浪源，比 akshare spot_em 稳）
        import sys
        from pathlib import Path
        ROOT = Path(__file__).resolve().parents[2]
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from sim.realtime_price import get_latest_prices

        codes = list(self.subscribed)
        prices = get_latest_prices(codes)

        for code in codes:
            data = prices.get(code)
            if not data:
                continue
            symbol_, exch = _norm_to_vt(code)
            try:
                price = float(data.get("price") or 0)
                if price <= 0:
                    continue
                tick = TickData(
                    gateway_name=self.gateway_name,
                    symbol=symbol_,
                    exchange=exch,
                    datetime=datetime.now(),
                    name=str(data.get("name") or symbol_),
                    last_price=price,
                    open_price=float(data.get("open") or price),
                    high_price=float(data.get("high") or price),
                    low_price=float(data.get("low") or price),
                    pre_close=float(data.get("yesterday_close") or 0),
                    volume=float(data.get("volume") or 0),
                    turnover=float(data.get("amount") or 0),
                    bid_price_1=price - 0.01,
                    ask_price_1=price + 0.01,
                    bid_volume_1=100,
                    ask_volume_1=100,
                )
                self.on_tick(tick)
            except Exception as e:
                logger.debug(f"{code} tick 推送失败: {e}")
