"""runners/run_backtest.py — vnpy CTA 回测器（K 线注入版）

数据源优先级：
  1) xtquant.xtdata.get_market_data（QMT 已下载本地数据）
  2) baostock 兜底（免费 A 股日线）

把拉到的 K 线转成 vnpy BarData 列表，**直接注入** `engine.history_data`，
跳过 vnpy 默认的数据库加载（无需配置 vnpy database manager）。

用法：
    .venv\\Scripts\\python.exe -m runners.run_backtest \\
        --code 600330 --start 20200101 --end 20240101

输出：
  - 控制台打印关键统计：胜率、最大回撤、夏普、交易次数
  - 带 --json <path> 时把统计写到 JSON 文件
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("run_backtest")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


# ---------------------------------------------------------------------------
# 数据源
# ---------------------------------------------------------------------------
def _exchange_for(code: str):
    """根据 6 位代码判断交易所"""
    from vnpy.trader.constant import Exchange
    return Exchange.SSE if code.startswith(("60", "68", "9", "5")) else Exchange.SZSE


def _xtquant_path() -> Optional[str]:
    candidates = [
        r"D:\国金QMT交易端模拟\bin.x64\Lib\site-packages",
        r"C:\Program Files\GJZQQMT\bin.x64\Lib\site-packages",
    ]
    for p in candidates:
        if Path(p, "xtquant").is_dir():
            return p
    return None


def fetch_bars_xtquant(code: str, start: str, end: str) -> List:
    """xtquant 路径，返回 vnpy BarData 列表（拉不到返回空列表）"""
    from vnpy.trader.object import BarData
    from vnpy.trader.constant import Interval

    xtq = _xtquant_path()
    if xtq is None:
        return []
    if xtq not in sys.path:
        sys.path.append(xtq)

    try:
        from xtquant import xtdata  # type: ignore
    except Exception as e:  # noqa: BLE001
        logger.warning("import xtquant 失败: %s", e)
        return []

    exch = _exchange_for(code)
    suffix = "SH" if exch.value == "SSE" else "SZ"
    symbol = f"{code}.{suffix}"

    try:
        data = xtdata.get_market_data(
            field_list=["open", "high", "low", "close", "volume"],
            stock_list=[symbol],
            period="1d",
            start_time=start,
            end_time=end,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("xtdata.get_market_data 异常: %s", e)
        return []

    o = data.get("open")
    if o is None or o.shape[1] == 0:
        return []

    bars: List[BarData] = []
    # 列是日期字符串，行 index 是 symbol
    for date_str in o.columns:
        try:
            dt = datetime.strptime(date_str, "%Y%m%d")
        except Exception:  # noqa: BLE001
            continue
        try:
            op = float(data["open"].at[symbol, date_str])
            hp = float(data["high"].at[symbol, date_str])
            lp = float(data["low"].at[symbol, date_str])
            cp = float(data["close"].at[symbol, date_str])
            vol = float(data["volume"].at[symbol, date_str])
        except Exception:  # noqa: BLE001
            continue
        if cp <= 0:
            continue
        bars.append(BarData(
            gateway_name="xtquant",
            symbol=code,
            exchange=exch,
            datetime=dt,
            interval=Interval.DAILY,
            volume=vol,
            open_price=op,
            high_price=hp,
            low_price=lp,
            close_price=cp,
        ))
    bars.sort(key=lambda b: b.datetime)
    logger.info("xtquant 拉到 %d 条 K 线 %s [%s~%s]", len(bars), symbol, start, end)
    return bars


def fetch_bars_baostock(code: str, start: str, end: str) -> List:
    """baostock 兜底，返回 vnpy BarData 列表"""
    import baostock as bs
    from vnpy.trader.object import BarData
    from vnpy.trader.constant import Interval

    exch = _exchange_for(code)
    bs_code = f"sh.{code}" if exch.value == "SSE" else f"sz.{code}"

    # baostock 的日期格式 yyyy-mm-dd
    s_fmt = f"{start[:4]}-{start[4:6]}-{start[6:]}"
    e_fmt = f"{end[:4]}-{end[4:6]}-{end[6:]}"

    rs = bs.login()
    if rs.error_code != "0":
        logger.error("baostock login 失败: %s", rs.error_msg)
        return []
    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume",
            start_date=s_fmt, end_date=e_fmt,
            frequency="d", adjustflag="2",  # 前复权
        )
        if rs.error_code != "0":
            logger.error("baostock 查询失败: %s", rs.error_msg)
            return []
        bars: List[BarData] = []
        while (rs.error_code == "0") and rs.next():
            row = rs.get_row_data()
            try:
                dt = datetime.strptime(row[0], "%Y-%m-%d")
                op, hp, lp, cp = float(row[1]), float(row[2]), float(row[3]), float(row[4])
                vol = float(row[5] or 0)
            except Exception:  # noqa: BLE001
                continue
            if cp <= 0:
                continue
            bars.append(BarData(
                gateway_name="baostock",
                symbol=code,
                exchange=exch,
                datetime=dt,
                interval=Interval.DAILY,
                volume=vol,
                open_price=op,
                high_price=hp,
                low_price=lp,
                close_price=cp,
            ))
        bars.sort(key=lambda b: b.datetime)
        logger.info("baostock 拉到 %d 条 K 线 %s [%s~%s]", len(bars), bs_code, start, end)
        return bars
    finally:
        bs.logout()


def fetch_bars(code: str, start: str, end: str) -> List:
    bars = fetch_bars_xtquant(code, start, end)
    if not bars:
        logger.info("xtquant 未取到数据，回退 baostock")
        bars = fetch_bars_baostock(code, start, end)
    return bars


# ---------------------------------------------------------------------------
# 回测
# ---------------------------------------------------------------------------
def run_backtest(code: str, start: str, end: str, capital: float = 100_000) -> dict:
    from vnpy.trader.constant import Exchange, Interval
    from vnpy_ctastrategy.backtesting import BacktestingEngine
    from strategies.threshold_alert_strategy import ThresholdAlertStrategy

    exch = _exchange_for(code)
    vt_symbol = f"{code}.{exch.value}"

    # 拉数据
    bars = fetch_bars(code, start, end)
    if not bars:
        logger.error("两路数据源都拉不到 K 线，无法回测")
        return {"error": "no_data", "code": code}

    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=vt_symbol,
        interval=Interval.DAILY,
        start=datetime.strptime(start, "%Y%m%d"),
        end=datetime.strptime(end, "%Y%m%d"),
        rate=0.0003,
        slippage=0.0,
        size=1,
        pricetick=0.01,
        capital=capital,
    )
    engine.add_strategy(ThresholdAlertStrategy, {})

    # 直接注入 history_data，跳过 vnpy 默认的数据库加载
    engine.history_data = bars

    engine.run_backtesting()
    df = engine.calculate_result()
    stats = engine.calculate_statistics(df, output=False) or {}

    # 整理输出
    summary = {
        "code": code,
        "vt_symbol": vt_symbol,
        "start": start,
        "end": end,
        "bars": len(bars),
        "trades": int(stats.get("total_trade_count") or engine.trade_count or 0),
        "total_return": float(stats.get("total_return", 0) or 0),
        "annual_return": float(stats.get("annual_return", 0) or 0),
        "max_drawdown": float(stats.get("max_drawdown", 0) or 0),
        "max_ddpercent": float(stats.get("max_ddpercent", 0) or 0),
        "sharpe_ratio": float(stats.get("sharpe_ratio", 0) or 0),
        "total_commission": float(stats.get("total_commission", 0) or 0),
        # 盈亏比 / 胜率：vnpy 默认统计里没有标准 win_rate，用 trades 简单估
    }
    # 简单估个胜率：按成交对盈亏算（一买一卖为一对）
    try:
        trades = list(engine.trades.values())
        # 按时间序列累计成本，pair 配对算盈亏
        pos = 0
        avg_cost = 0.0
        wins, losses = 0, 0
        for t in sorted(trades, key=lambda x: x.datetime):
            qty = t.volume
            price = t.price
            if t.direction.value == "多":
                # 买入
                new_pos = pos + qty
                if new_pos > 0:
                    avg_cost = (avg_cost * pos + price * qty) / new_pos
                pos = new_pos
            else:
                # 卖出
                if pos > 0:
                    pnl = (price - avg_cost) * min(qty, pos)
                    if pnl > 0:
                        wins += 1
                    else:
                        losses += 1
                    pos -= qty
        total = wins + losses
        summary["closed_trades"] = total
        summary["wins"] = wins
        summary["losses"] = losses
        summary["win_rate"] = (wins / total) if total else 0.0
    except Exception as e:  # noqa: BLE001
        logger.warning("胜率统计失败: %s", e)
        summary["win_rate"] = None

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--code", default="600330")
    p.add_argument("--start", default="20200101")
    p.add_argument("--end", default="20240101")
    p.add_argument("--capital", type=float, default=100_000)
    p.add_argument("--json", dest="json_out", default=None,
                   help="把结果写到 JSON 文件")
    return p.parse_args()


def main():
    args = parse_args()
    summary = run_backtest(args.code, args.start, args.end, args.capital)
    print("\n========== 回测结果 ==========")
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k:<18} = {v:.4f}")
        else:
            print(f"  {k:<18} = {v}")
    print("==============================\n")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"已写入 {out}")


if __name__ == "__main__":
    main()
