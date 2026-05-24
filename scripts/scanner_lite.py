"""scripts/scanner_lite.py — AKShare 降级版扫描器

背景：AKShare 在云桌面被限流，morning_scanner 的 ak.stock_zh_a_spot_em / 
index_stock_cons / stock_zh_a_hist 全部不可用（2026-05-24 验证）。

降级方案：
- 股票池：watchlist + E2 推荐 + 当前持仓（约 30-40 只，不用全市场）
- 实时行情：新浪 hq.sinajs.cn （盘中可用，与 sim/realtime_price 同源）
- 历史 K 线：baostock（可用）
- 打分逻辑：复用 morning_scanner.calc_factors（趋势/突破/量能/区间 4 因子）

这个脚本意在**作为 morning_scanner 的兜底**：
- AKShare 通时用 morning_scanner（全 800 股扫描）
- AKShare 不通时用 scanner_lite（30 股精选，覆盖率低但能跑）

用法：
    python scripts/scanner_lite.py             # 扫描 + 推送
    python scripts/scanner_lite.py --top 5     # 只显示前 5
    python scripts/scanner_lite.py --no-webhook
"""
from __future__ import annotations
import sys
import time
import argparse
import logging
import json
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml
import pandas as pd
import baostock as bs

# 复用 morning_scanner 的打分函数
from scripts.morning_scanner import calc_factors  # type: ignore
from sim.realtime_price import fetch_sina_realtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("scanner_lite")

# E2 严格筛选 + F 扫描里表现稳定的股票池（来自 2026-05-24 周末回测）
E2_F_PICKS = [
    # E2 A 档 4 只
    "000967",  # 盈峰环境 复合
    "002920",  # 德赛西威 复合 (夏普 6.08)
    "600703",  # 三安光电 MACD
    "002256",  # 兆新股份 MACD
    # F 扫描表现好的扩展候选
    "002453",  # 华软科技
    "600330",  # 天通股份
    "300059",  # 东方财富
    "603290",  # 斯达半导
    "300124",  # 汇川技术
    "002475",  # 立讯精密
    # watchlist 长线 (来自 data/watchlist_notes.json)
    "000301",  # 东方盛虹
    "603260",  # 合盛硅业
    "600563",  # 法拉电子
    "000708",  # 中信特钢
    "002906",  # 华阳集团
    "603013",  # 亚普股份
    "002405",  # 四维图新
    # 主流龙头作对照基准
    "300750",  # 宁德时代
    "002594",  # 比亚迪
    "601012",  # 隆基绿能
]


def get_holdings_codes() -> list[str]:
    """从 portfolio.yaml + sim DB 读当前持仓"""
    codes = set()
    cfg_path = ROOT / "vqlearn" / "config" / "portfolio.yaml"
    if cfg_path.exists():
        try:
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            for h in cfg.get("holdings", []) or []:
                if int(h.get("qty", 0)) > 0:
                    codes.add(str(h["symbol"]))
            for w in cfg.get("watchlist", []) or []:
                codes.add(str(w["symbol"]))
        except Exception as e:
            logger.warning(f"读 portfolio.yaml 失败: {e}")
    # sim DB
    import sqlite3
    db = ROOT / "data" / "sim_live_mirror.db"
    if db.exists():
        try:
            conn = sqlite3.connect(str(db))
            for row in conn.execute("SELECT stock_code FROM sim_positions WHERE quantity > 0"):
                codes.add(str(row[0]))
            conn.close()
        except Exception as e:
            logger.warning(f"读 sim DB 失败: {e}")
    return sorted(codes)


def build_universe() -> list[str]:
    pool = set(E2_F_PICKS) | set(get_holdings_codes())
    return sorted(pool)


def get_kline_bs(code: str, days: int = 30) -> pd.DataFrame | None:
    """baostock 拉历史日线，转成 morning_scanner.calc_factors 期望的格式（中文列名）"""
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days * 2 + 30)).strftime("%Y-%m-%d")

    prefix = "sh" if code.startswith("6") else "sz"
    bs_code = f"{prefix}.{code}"
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,volume",
        start_date=start, end_date=end,
        frequency="d", adjustflag="2",  # 前复权
    )
    if rs.error_code != "0":
        return None
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    df = df[df["close"] > 0]
    # 重命名为 calc_factors 期望的中文列名
    df = df.rename(columns={
        "open": "开盘", "high": "最高", "low": "最低",
        "close": "收盘", "volume": "成交量", "date": "日期",
    })
    return df.tail(days).reset_index(drop=True) if len(df) >= 20 else None


def scan(top_n: int = 10, post_webhook: bool = True) -> list[dict]:
    universe = build_universe()
    logger.info(f"股票池: {len(universe)} 只 = E2/F {len(E2_F_PICKS)} + 持仓/关注 {len(universe)-len(E2_F_PICKS)}")

    # 实时行情（新浪）
    logger.info("拉实时行情（新浪）...")
    realtime = fetch_sina_realtime(universe)
    if not realtime:
        logger.error("新浪实时行情全失败！")
        return []
    logger.info(f"  实时取到 {len(realtime)}/{len(universe)}")

    # 历史 K 线（baostock，带 login 一次性）
    logger.info("拉历史 K 线（baostock）...")
    bs.login()

    results = []
    try:
        for i, code in enumerate(universe, 1):
            spot = realtime.get(code)
            if not spot or spot["price"] <= 0:
                continue
            try:
                hist = get_kline_bs(code, days=30)
            except Exception as e:
                logger.debug(f"{code} K线失败: {e}")
                continue
            if hist is None or len(hist) < 20:
                continue

            # 把今天的最新价作为 K 线最后一行的"今日"价（盘中实时）
            # 否则只看到昨日数据，量比/突破都不准
            now_hour = datetime.now().hour
            if 9 <= now_hour < 16:  # 盘中
                # 在末尾追加一行"伪今日"
                today_row = pd.DataFrame([{
                    "日期": datetime.now().strftime("%Y-%m-%d"),
                    "开盘": spot["open"], "最高": spot["high"],
                    "最低": spot["low"], "收盘": spot["price"],
                    "成交量": spot["volume"],
                }])
                hist = pd.concat([hist, today_row], ignore_index=True)

            try:
                r = calc_factors(code, hist, None)
            except Exception as e:
                logger.debug(f"{code} 打分失败: {e}")
                continue
            if r is None:
                continue
            r["name"] = spot.get("name") or code
            r["realtime_price"] = spot["price"]
            results.append(r)
    finally:
        bs.logout()

    results.sort(key=lambda x: -x["score"])
    return results[:top_n] if top_n > 0 else results


def render(results: list[dict]) -> str:
    if not results:
        return "❌ 扫描无结果"
    lines = [
        f"🔍 Lite Scanner ({datetime.now():%Y-%m-%d %H:%M})  N={len(results)}",
        "数据源：新浪实时 + baostock 历史（AKShare 降级版）",
        "",
        f"{'排名':<4}{'代码':<8}{'名称':<10}{'价格':>8}{'涨幅':>7}{'分':>6}{'趋势':>6}{'突破':>6}{'量能':>6}{'区间':>6}",
        "─" * 78,
    ]
    for i, r in enumerate(results, 1):
        f = r["factors"]
        lines.append(
            f"{i:<4}{r['code']:<8}{r['name'][:6]:<10}{r['price']:>7.2f} "
            f"{r['pct_chg']:>+6.2f}% {r['score']:>5d}  "
            f"{f['trend']:>4d}  {f['breakout']:>4d}  {f['volume']:>4d}  {f['zone']:>4d}"
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--no-webhook", action="store_true")
    ap.add_argument("--save", default=None, help="保存 JSON 到文件")
    args = ap.parse_args()

    t0 = time.time()
    results = scan(top_n=args.top, post_webhook=not args.no_webhook)
    elapsed = time.time() - t0

    print(render(results))
    print(f"\n⏱  用时 {elapsed:.1f}s | 数据源: 新浪+baostock | 股票池: E2/F + 持仓")

    if args.save:
        Path(args.save).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ 已保存到 {args.save}")


if __name__ == "__main__":
    main()
