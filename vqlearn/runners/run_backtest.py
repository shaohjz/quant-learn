"""
vqlearn/runners/run_backtest.py — 离线回测验证

不依赖 vnpy 数据库，直接用 akshare 拉历史日 K 线，
把每只股票每天的 close 当 tick 喂给 ThresholdAlertStrategy 实例，
检查阈值规则在过去 N 天里会不会触发。

用法：
  python vqlearn/runners/run_backtest.py --days 30
"""
from __future__ import annotations

import sys
import io
import logging
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backtest")

from vnpy.trader.object import TickData, ContractData
from vnpy.trader.constant import Exchange, Product

from vqlearn.gateways.akshare_gateway import _norm_to_vt
from vqlearn.strategies.threshold_strategy import ThresholdAlertStrategy

CONFIG_PATH = ROOT / "vqlearn" / "config" / "portfolio.yaml"


class FakeCtaEngine:
    """伪装的 CtaEngine，只接收 buy/sell/log 调用"""
    def __init__(self):
        self.trade_log = []
        self.alert_log = []

    def call_strategy_func(self, strategy, func, params=None):
        if params is None:
            return func()
        return func(params)

    def write_log(self, msg, strategy):
        # 收集日志
        if any(k in msg for k in ["🔴", "🟢", "🟡", "💰", "buy_zone", "buy_strong", "trend_break", "take_profit"]):
            self.alert_log.append((strategy.vt_symbol, msg))

    def send_order(self, strategy, direction, offset, price, volume, stop, lock, net):
        self.trade_log.append({
            "symbol": strategy.vt_symbol,
            "direction": direction.value,
            "offset": offset.value,
            "price": price,
            "volume": volume,
        })
        return [f"fake_order_{len(self.trade_log)}"]

    def cancel_order(self, strategy, vt_orderid):
        pass

    def put_strategy_event(self, strategy):
        pass

    def get_pricetick(self, strategy):
        return 0.01

    def get_size(self, strategy):
        return 1

    def get_engine_type(self):
        from vnpy_ctastrategy.base import EngineType
        return EngineType.BACKTESTING

    def sync_strategy_data(self, strategy):
        pass


def fetch_history(symbol: str, days: int) -> list[dict]:
    """先试新浪（稳），失败退 akshare"""
    import requests
    import re

    # 加市场前缀
    if symbol.startswith(("60", "68", "11", "12", "5")):
        sina_code = f"sh{symbol}"
    elif symbol.startswith(("00", "30", "15", "16")):
        sina_code = f"sz{symbol}"
    elif symbol.startswith(("83", "87", "92", "43")):
        sina_code = f"bj{symbol}"
    else:
        sina_code = f"sh{symbol}"

    url = "https://quotes.sina.cn/cn/api/jsonp_v2.php/var=_aux=/CN_MarketDataService.getKLineData"
    params = {"symbol": sina_code, "scale": 240, "ma": "no", "datalen": days}
    try:
        r = requests.get(url, params=params, timeout=10)
        text = r.text
        m = re.search(r"\[.*\]", text)
        if not m:
            return []
        import json
        data = json.loads(m.group(0))
        bars = []
        for d in data:
            try:
                bars.append({
                    "date": d["day"],
                    "open": float(d["open"]),
                    "high": float(d["high"]),
                    "low": float(d["low"]),
                    "close": float(d["close"]),
                })
            except Exception:
                continue
        return bars
    except Exception as e:
        logger.warning(f"新浪 {symbol} 失败 ({e})，试 akshare")

    # akshare 备选
    try:
        import akshare as ak
        end = datetime.now()
        start = end - timedelta(days=days * 2)
        df = ak.stock_zh_a_hist(
            symbol=symbol, period="daily", adjust="qfq",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if df is None or len(df) == 0:
            return []
        bars = []
        for _, row in df.iterrows():
            try:
                bars.append({
                    "date": str(row["日期"]),
                    "open": float(row["开盘"]),
                    "high": float(row["最高"]),
                    "low": float(row["最低"]),
                    "close": float(row["收盘"]),
                })
            except Exception:
                continue
        return bars[-days:]
    except Exception:
        return []


def run_backtest(days: int = 30) -> None:
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    holdings = cfg.get("holdings", [])
    watchlist = cfg.get("watchlist", [])
    all_items = [{**h, "is_holding": True} for h in holdings] + [{**w, "is_holding": False} for w in watchlist]

    print(f"\n{'='*80}")
    print(f"📊 vqlearn 回测：过去 {days} 天 | {len(all_items)} 只股票")
    print(f"{'='*80}\n")

    engine = FakeCtaEngine()
    triggers_per_stock = {}

    for item in all_items:
        symbol = item["symbol"]
        name = item.get("name", symbol)
        rules = item.get("rules") or {}
        if not rules:
            continue

        symbol_norm, exch = _norm_to_vt(symbol)
        vt_symbol = f"{symbol_norm}.{exch.value}"

        setting = {
            "buy_zone": float(rules.get("buy_zone") or 0),
            "buy_strong": float(rules.get("buy_strong") or 0),
            "trend_break": float(rules.get("trend_break") or 0),
            "take_profit": float(rules.get("take_profit") or 0),
            "fixed_size": 100,
            "auto_trade": True,
        }

        strategy = ThresholdAlertStrategy(engine, f"thr_{symbol}", vt_symbol, setting)
        strategy.inited = True
        strategy.trading = True
        # 持仓填进去
        if item.get("is_holding"):
            strategy.pos = int(item.get("qty") or 0)

        bars = fetch_history(symbol, days)
        if not bars:
            print(f"  ⚠️ {symbol} {name} 无历史数据")
            continue

        # 记录该股票的触发
        triggers = []
        before_count = len(engine.alert_log)

        # 喂 tick：每个交易日喂 high/low/close 三个 tick（high 和 low 测涨跌穿透）
        for bar in bars:
            for price_field in ["low", "close", "high"]:
                price = bar[price_field]
                tick = TickData(
                    gateway_name="BACKTEST",
                    symbol=symbol_norm,
                    exchange=exch,
                    datetime=datetime.strptime(bar["date"], "%Y-%m-%d"),
                    last_price=price,
                    pre_close=price,
                )
                # 直接调内部检查，绕过 vnpy 事件
                strategy.last_price = price
                strategy._check_rules(tick)
            # 每天结束清空 fired_today（让规则可重复触发）
            # 但这里 _check_rules 内部已经按 date 去重，跨天会自动重置

        after_count = len(engine.alert_log)
        new_alerts = engine.alert_log[before_count:after_count]
        triggers_per_stock[symbol] = {
            "name": name,
            "is_holding": item.get("is_holding"),
            "qty": item.get("qty", 0),
            "rules": setting,
            "alerts": new_alerts,
            "first_price": bars[0]["close"] if bars else 0,
            "last_price": bars[-1]["close"] if bars else 0,
            "low_price": min(b["low"] for b in bars),
            "high_price": max(b["high"] for b in bars),
        }

    # ---- 输出报告 ----
    print(f"\n{'='*80}")
    print(f"📋 回测报告（{days} 天）")
    print(f"{'='*80}\n")

    holding_alerts = []
    watchlist_alerts = []
    for symbol, info in triggers_per_stock.items():
        if info["alerts"]:
            (holding_alerts if info["is_holding"] else watchlist_alerts).append((symbol, info))

    print(f"🏠 持仓触发：{len(holding_alerts)} 只\n")
    for symbol, info in holding_alerts:
        print(f"  📌 {symbol} {info['name']} (持仓 {info['qty']}股, 区间 {info['low_price']:.2f}~{info['high_price']:.2f}, 当前 {info['last_price']:.2f})")
        for vt, msg in info["alerts"]:
            print(f"     {msg}")
        print()

    print(f"\n👀 观察池触发：{len(watchlist_alerts)} 只\n")
    for symbol, info in watchlist_alerts:
        print(f"  📌 {symbol} {info['name']} (区间 {info['low_price']:.2f}~{info['high_price']:.2f}, 当前 {info['last_price']:.2f})")
        for vt, msg in info["alerts"]:
            print(f"     {msg}")
        print()

    no_trigger = [s for s, i in triggers_per_stock.items() if not i["alerts"]]
    print(f"\n💤 无触发：{len(no_trigger)} 只 → {', '.join(no_trigger)}")

    # 统计
    print(f"\n{'='*80}")
    print(f"📈 统计")
    print(f"{'='*80}")
    print(f"  总触发次数: {len(engine.alert_log)}")
    print(f"  虚拟成交次数: {len(engine.trade_log)}")
    if engine.trade_log:
        buy_count = sum(1 for t in engine.trade_log if t["direction"] == "多")
        sell_count = sum(1 for t in engine.trade_log if t["direction"] == "空")
        print(f"  └─ BUY: {buy_count} | SELL: {sell_count}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    args = p.parse_args()
    run_backtest(args.days)
