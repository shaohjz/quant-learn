"""
vqlearn/runners/run_paper.py — 启动 vnpy MainEngine

架构：
  AkshareGateway（行情 only） → 推 TickData → EventEngine
                                              ├→ PaperAccount（虚拟撮合）
                                              └→ Strategy（CtaStrategy）

特性：
  - 全 vnpy 标准事件驱动
  - 持仓自动从配置加载
  - 模拟下单，无真单风险
  - 数据持久化到 vnpy.database (SQLite)
"""
from __future__ import annotations

import sys
import time
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import io
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("paper-runner")

from vnpy.event import EventEngine, Event
from vnpy.trader.engine import MainEngine
from vnpy.trader.event import EVENT_TICK, EVENT_TRADE, EVENT_ORDER, EVENT_LOG
from vnpy.trader.object import SubscribeRequest
from vnpy.trader.constant import Exchange

from vqlearn.gateways.akshare_gateway import AkshareGateway, _norm_to_vt
try:
    from vnpy_paperaccount import PaperAccountApp
except ImportError:
    PaperAccountApp = None
    logger.warning("vnpy_paperaccount 未安装，跳过虚拟账户")

# ===== 持仓 + 观察池配置 =====
HOLDINGS = [
    "600330",  # 天通股份
    "002256",  # 兆新股份
    "002453",  # 华软科技
    "603601",  # 再升科技
]

WATCHLIST = [
    # 昨晚 + 今天加的观察池
    "002428", "600130", "603178", "603986",
    # 绿电板块
    "301120", "301179", "600021", "000600", "002067",
    "000899", "001896", "600310", "601222", "600863", "600330",
    # 其他观察
    "605006", "603757", "002156", "002709", "002149",
]

ALL_SYMBOLS = list(dict.fromkeys(HOLDINGS + WATCHLIST))


def setup_engine() -> tuple[MainEngine, EventEngine]:
    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)

    # 添加 akshare gateway（行情 only）
    main_engine.add_gateway(AkshareGateway)

    # 添加 paper account app（虚拟撮合）
    if PaperAccountApp:
        main_engine.add_app(PaperAccountApp)
        logger.info("✓ PaperAccount 已加载")

    return main_engine, event_engine


def hook_logging(event_engine: EventEngine) -> None:
    """订阅 vnpy 事件做日志输出"""
    seen_ticks = {}

    def on_tick(event: Event):
        tick = event.data
        key = f"{tick.symbol}.{tick.exchange.value}"
        prev = seen_ticks.get(key)
        # 只在价格变化时打日志（不刷屏）
        if prev is None or abs(prev - tick.last_price) > 1e-6:
            logger.info(
                f"📊 TICK {key} {tick.name} last={tick.last_price:.2f} "
                f"open={tick.open_price:.2f} pre_close={tick.pre_close:.2f} "
                f"chg={(tick.last_price/tick.pre_close-1)*100:+.2f}%"
                if tick.pre_close > 0 else
                f"📊 TICK {key} last={tick.last_price:.2f}"
            )
            seen_ticks[key] = tick.last_price

    def on_trade(event: Event):
        trade = event.data
        logger.info(f"💰 TRADE {trade.symbol} {trade.direction.value} {trade.volume}@{trade.price:.2f}")

    def on_order(event: Event):
        order = event.data
        logger.info(f"📋 ORDER {order.symbol} {order.direction.value} {order.volume}@{order.price:.2f} status={order.status.value}")

    def on_log(event: Event):
        log = event.data
        logger.info(f"[{log.gateway_name}] {log.msg}")

    event_engine.register(EVENT_TICK, on_tick)
    event_engine.register(EVENT_TRADE, on_trade)
    event_engine.register(EVENT_ORDER, on_order)
    event_engine.register(EVENT_LOG, on_log)


def main(timeout: int = 0) -> None:
    logger.info("=== vqlearn paper trading runner ===")
    logger.info(f"持仓 {len(HOLDINGS)} 只，观察 {len(WATCHLIST)} 只，去重后总计 {len(ALL_SYMBOLS)} 只")

    main_engine, event_engine = setup_engine()
    hook_logging(event_engine)

    # 连接 akshare gateway
    main_engine.connect({"轮询间隔(秒)": 5}, "AKSHARE")
    time.sleep(1)  # 等线程启动

    # 订阅所有合约
    gateway = main_engine.get_gateway("AKSHARE")
    from vnpy.trader.object import ContractData
    from vnpy.trader.constant import Product

    # 第一轮：只 push contract，让 OMS / PaperAccount 记录下来
    pending_subs = []
    for code in ALL_SYMBOLS:
        symbol, exch = _norm_to_vt(code)
        contract = ContractData(
            gateway_name="AKSHARE",
            symbol=symbol,
            exchange=exch,
            name=symbol,
            product=Product.EQUITY,
            size=1,
            pricetick=0.01,
        )
        gateway.on_contract(contract)
        pending_subs.append((symbol, exch))

    # 等事件队列消化完 contract 事件
    time.sleep(1)

    # 第二轮：才 subscribe。这时 PaperAccount.gateway_map 已填好
    for symbol, exch in pending_subs:
        req = SubscribeRequest(symbol=symbol, exchange=exch)
        main_engine.subscribe(req, "AKSHARE")

    logger.info(f"✓ 已订阅 {len(ALL_SYMBOLS)} 只合约，开始盘中行情推送...")
    if timeout > 0:
        logger.info(f"limited mode: 运行 {timeout}s 后退出")
    else:
        logger.info("按 Ctrl+C 退出")

    end_at = time.time() + timeout if timeout > 0 else None
    try:
        while True:
            time.sleep(15)
            logger.info(f"♥ 引擎心跳，订阅 {len(ALL_SYMBOLS)} 只")
            if end_at and time.time() >= end_at:
                logger.info("达到 timeout，退出")
                break
    except KeyboardInterrupt:
        logger.info("用户中断，正在关闭...")
    finally:
        main_engine.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--timeout", type=int, default=0, help="运行多少秒后退出，0=永久")
    args = p.parse_args()
    main(args.timeout)
