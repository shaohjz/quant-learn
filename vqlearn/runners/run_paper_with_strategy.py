"""
vqlearn/runners/run_paper_with_strategy.py — vnpy 完整闭环 runner

链路：
  AkshareGateway（行情）
    → EVENT_TICK
       → CtaEngine（策略引擎）
          → ThresholdAlertStrategy 实例 × N（每只股票一个）
             → on_tick 触发阈值
                → self.buy()/self.sell()
                   → PaperAccount（虚拟撮合）
                      → EVENT_TRADE
"""
from __future__ import annotations

import sys
import time
import logging
import yaml
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
logger = logging.getLogger("paper-strat")

from vnpy.event import EventEngine, Event
from vnpy.trader.engine import MainEngine
from vnpy.trader.event import EVENT_TICK, EVENT_TRADE, EVENT_ORDER, EVENT_LOG
from vnpy.trader.object import SubscribeRequest, ContractData
from vnpy.trader.constant import Exchange, Product

from vqlearn.gateways.akshare_gateway import AkshareGateway, _norm_to_vt
from vqlearn.strategies.threshold_strategy import ThresholdAlertStrategy

from vnpy_paperaccount import PaperAccountApp
from vnpy_ctastrategy import CtaStrategyApp
from vnpy_ctastrategy.engine import CtaEngine

CONFIG_PATH = ROOT / "vqlearn" / "config" / "portfolio.yaml"


def _fetch_5d_avg_volumes(codes: list[str]) -> dict[str, float]:
    """拉近 5 个交易日的日 K 线，计算 avg_vol（股数）。优先新浪。"""
    import akshare as ak
    from datetime import date, timedelta
    avg = {}
    end = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=15)).strftime("%Y%m%d")
    for code in codes:
        # 新浪 code prefix
        if code.startswith(('60', '68', '11', '12', '5')):
            sina_code = 'sh' + code
        elif code.startswith(('00', '30', '15', '16')):
            sina_code = 'sz' + code
        else:
            sina_code = 'sh' + code
        try:
            df = ak.stock_zh_a_daily(symbol=sina_code, start_date=start, end_date=end, adjust='qfq')
            if df is None or len(df) < 5:
                continue
            tail5 = df.tail(5)
            v = float(tail5['volume'].mean())  # 新浪 volume 单位是股
            avg[code] = v
        except Exception as e:
            logger.debug(f"avg_vol_5d 拉取失败 {code}: {e}")
    return avg


def load_portfolio() -> tuple[list[dict], list[dict]]:
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return cfg.get("holdings", []), cfg.get("watchlist", [])


def hook_logging(event_engine: EventEngine) -> None:
    seen_ticks = {}

    def on_tick(event: Event):
        tick = event.data
        key = f"{tick.symbol}.{tick.exchange.value}"
        prev = seen_ticks.get(key)
        if prev is None or abs(prev - tick.last_price) > 1e-6:
            chg = (tick.last_price/tick.pre_close-1)*100 if tick.pre_close > 0 else 0
            logger.info(f"📊 TICK {key} {tick.name} {tick.last_price:.2f} ({chg:+.2f}%)")
            seen_ticks[key] = tick.last_price

    def on_trade(event: Event):
        t = event.data
        logger.info(f"💰 TRADE {t.symbol} {t.direction.value} {t.volume}@{t.price:.2f}")

    def on_log(event: Event):
        log = event.data
        msg = log.msg
        if "找不到该合约" in msg:
            return
        logger.info(f"[{log.gateway_name}] {msg}")

    event_engine.register(EVENT_TICK, on_tick)
    event_engine.register(EVENT_TRADE, on_trade)
    event_engine.register(EVENT_LOG, on_log)


def main(timeout: int = 0, auto_trade: bool = False) -> None:
    holdings, watchlist = load_portfolio()
    logger.info(f"=== vqlearn paper + strategy ===")
    logger.info(f"持仓: {len(holdings)} 只 | 观察: {len(watchlist)} 只 | auto_trade={auto_trade}")

    # ---- 1. 初始化引擎 ----
    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    main_engine.add_gateway(AkshareGateway)
    main_engine.add_app(PaperAccountApp)
    cta_engine: CtaEngine = main_engine.add_app(CtaStrategyApp)
    hook_logging(event_engine)

    # ---- 2. 启动 gateway ----
    main_engine.connect({"轮询间隔(秒)": 5}, "AKSHARE")
    time.sleep(1)

    # ---- 3. 推 contract + 订阅 ----
    gateway = main_engine.get_gateway("AKSHARE")
    all_items = []
    for h in holdings:
        all_items.append({**h, "is_holding": True})
    for w in watchlist:
        all_items.append({**w, "is_holding": False})

    pending_subs = []
    for item in all_items:
        symbol, exch = _norm_to_vt(item["symbol"])
        contract = ContractData(
            gateway_name="AKSHARE",
            symbol=symbol,
            exchange=exch,
            name=item.get("name", symbol),
            product=Product.EQUITY,
            size=1,
            pricetick=0.01,
        )
        gateway.on_contract(contract)
        pending_subs.append((item, symbol, exch))

    time.sleep(1)  # 等 EVENT_CONTRACT 流转

    for item, symbol, exch in pending_subs:
        req = SubscribeRequest(symbol=symbol, exchange=exch)
        main_engine.subscribe(req, "AKSHARE")

    # ---- 4. 初始化 CtaEngine ----
    cta_engine.init_engine()
    time.sleep(1)

    # 显式加载我们的策略类（vnpy 默认只扫 strategies/ 和 vnpy_ctastrategy.strategies）
    cta_engine.load_strategy_class_from_module("vqlearn.strategies.threshold_strategy")
    logger.info(f"已加载策略类: {list(cta_engine.classes.keys())}")

    # ---- 5. 给每只股票装一个 ThresholdAlertStrategy 实例 ----
    loaded = 0
    for item, symbol, exch in pending_subs:
        rules = item.get("rules") or {}
        if not rules:
            continue
        vt_symbol = f"{symbol}.{exch.value}"
        instance_name = f"thr_{symbol}"
        setting = {
            "buy_zone": float(rules.get("buy_zone") or 0),
            "buy_strong": float(rules.get("buy_strong") or 0),
            "trend_break": float(rules.get("trend_break") or 0),
            "take_profit": float(rules.get("take_profit") or 0),
            "fixed_size": 100,
            "auto_trade": bool(auto_trade),
        }
        try:
            cta_engine.add_strategy(
                class_name="ThresholdAlertStrategy",
                strategy_name=instance_name,
                vt_symbol=vt_symbol,
                setting=setting,
            )
            # 注入 stock_name（sim_executor 要用）
            strat = cta_engine.strategies.get(instance_name)
            if strat is not None:
                strat.stock_name = item.get("name", symbol)
            loaded += 1
        except Exception as e:
            logger.warning(f"加载策略 {instance_name} 失败: {e}")

    logger.info(f"✓ 已加载 {loaded} 个 ThresholdAlertStrategy 实例")

    # ---- 5b. 拉 5 日均量注入各策略 ----
    try:
        codes = [s.split('.')[0] for s in (cta_engine.symbol_strategy_map.keys() if hasattr(cta_engine, 'symbol_strategy_map') else [])]
        if not codes:
            codes = [item['symbol'] for item, _, _ in pending_subs]
        logger.info(f"📊 拉取 5 日均量 {len(codes)} 只...")
        avg_vols = _fetch_5d_avg_volumes(codes)
        logger.info(f"   获得 {len(avg_vols)} 只均量")
        for name, strat in cta_engine.strategies.items():
            code = strat.vt_symbol.split('.')[0]
            if code in avg_vols:
                strat.avg_vol_5d = avg_vols[code]
        sample = list(avg_vols.items())[:3]
        logger.info(f"   样本: {sample}")
    except Exception as e:
        logger.warning(f"拉取 5 日均量失败，量过滤可能不生效: {e}")

    # 初始化所有策略
    for name in list(cta_engine.strategies.keys()):
        cta_engine.init_strategy(name)
    time.sleep(2)
    for name in list(cta_engine.strategies.keys()):
        cta_engine.start_strategy(name)

    logger.info(f"🚀 全部 {loaded} 个策略已启动")
    if timeout > 0:
        logger.info(f"limited mode: {timeout}s 后退出")

    # ---- 6. 主循环 ----
    end_at = time.time() + timeout if timeout > 0 else None
    last_close_confirm = None  # 防重复处理

    def _maybe_run_close_confirm():
        nonlocal last_close_confirm
        from datetime import datetime as _dt, time as _tt, date as _date
        n = _dt.now()
        if last_close_confirm == _date.today():
            return
        if not (_tt(14, 55) <= n.time() <= _tt(15, 5)):
            return
        # 从 all_ticks 里拿最新价当作收盘价
        from vqlearn.services.threshold_state import mark_close_confirm_for_all_pending
        ticks = main_engine.get_all_ticks()
        price_map = {t.symbol: t.last_price for t in ticks if t.last_price > 0}
        upgraded, expired = mark_close_confirm_for_all_pending(
            lambda code: price_map.get(code)
        )
        last_close_confirm = _date.today()
        logger.info(f"🔔 收盘价确认: armed={len(upgraded)} expired={len(expired)}")
        for r in upgraded:
            logger.info(f"   ✅ armed: {r}")
        for r in expired:
            logger.info(f"   ♻️ expired: {r}")

    try:
        while True:
            time.sleep(15)
            logger.info(f"♥ 心跳 | 策略 {len(cta_engine.strategies)} 个 | tick {len(main_engine.get_all_ticks())}")
            try:
                _maybe_run_close_confirm()
            except Exception as e:
                logger.warning(f"收盘确认出错: {e}")
            if end_at and time.time() >= end_at:
                logger.info("达到 timeout")
                break
    except KeyboardInterrupt:
        logger.info("用户中断")
    finally:
        for name in list(cta_engine.strategies.keys()):
            cta_engine.stop_strategy(name)
        main_engine.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--timeout", type=int, default=0)
    p.add_argument("--auto-trade", action="store_true", help="开启自动下单")
    args = p.parse_args()
    main(args.timeout, args.auto_trade)
