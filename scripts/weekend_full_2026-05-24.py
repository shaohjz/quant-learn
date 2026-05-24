"""周末扩展回测 2026-05-24

四件事：
  A. 扩股票池 (4 → 30+) + 数据更新到 2026-05-23 + 全策略矩阵回测
  B. MACD 参数扫描 (fast/slow/signal grid)
  C. Walk-forward / out-of-sample 检验 (前 70% in-sample, 后 30% out-of-sample)
  D. 新策略：量价突破 (volume_breakout)

输出：
  - data/<code>.csv              数据更新
  - output/weekly_full_2026-05-24/
      ├── A_universe_matrix.md   扩样本回测结果
      ├── B_macd_gridsearch.md   MACD 参数扫描
      ├── C_walkforward.md       样本外检验
      ├── D_new_strategy.md      量价突破策略结果
      └── summary.md             综合周报
"""
from __future__ import annotations
import sys
import os
import time
import io
import json
import contextlib
import warnings
import itertools
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")

import backtrader as bt
import backtrader.analyzers as btanalyzers

# 禁用 cerebro.plot（无 GUI 卡死）
bt.Cerebro.plot = lambda self, *a, **kw: [[None]]

import pandas as pd

try:
    import akshare as ak
    HAS_AK = True
except Exception:
    HAS_AK = False

try:
    import baostock as bs
    HAS_BS = True
except Exception:
    HAS_BS = False

from backtest import (  # noqa: E402
    run_backtest,
    STOCK_NAMES,
    StampDutyCommission,
    DATA_DIR,
    OUTPUT_DIR,
)

OUT_ROOT = Path(OUTPUT_DIR) / "weekly_full_2026-05-24"
OUT_ROOT.mkdir(parents=True, exist_ok=True)

# 扩展股票池：原 4 只 + watchlist 10 只 + 持仓 3 只 + 主流龙头 + 你关注的 600130/600310
EXPANDED_UNIVERSE = {
    # 原有 4 只
    "000967": "盈峰环境",
    "002256": "兆新股份",
    "002453": "华软科技",
    "600330": "天通股份",
    # watchlist (长线)
    "000301": "东方盛虹",
    "603260": "合盛硅业",
    "603290": "斯达半导",
    "600703": "三安光电",
    "000708": "中信特钢",
    "600563": "法拉电子",
    "002906": "华阳集团",
    "603013": "亚普股份",
    "002405": "四维图新",
    "002920": "德赛西威",
    # 持仓 (sim_live_mirror)
    "600130": "波导股份",
    "600310": "广西能源",
    # 主流龙头 / 测试基准
    "600519": "贵州茅台",
    "000858": "五粮液",
    "300750": "宁德时代",
    "002594": "比亚迪",
    "600036": "招商银行",
    "601318": "中国平安",
    "000333": "美的集团",
    "002415": "海康威视",
    "300059": "东方财富",
    "601012": "隆基绿能",
    "300760": "迈瑞医疗",
    "600276": "恒瑞医药",
    "002475": "立讯精密",
    "300124": "汇川技术",
    "600887": "伊利股份",
}

STRATEGIES = ["sma_cross", "macd_strategy", "bollinger_strategy", "composite", "composite_v2"]
INIT_CASH = 100_000.0

# 高价股需要更多本金才能买得起 100 股／FixedSize stake=100
HIGH_PRICE_CASH = 500_000.0
HIGH_PRICE_THRESHOLD = 100.0  # 股价 ≥ 100 元则用高价本金


def _cash_for(code: str) -> float:
    """根据最近股价调整本金"""
    try:
        df = pd.read_csv(Path(DATA_DIR) / f"{code}.csv")
        last = float(df["close"].iloc[-1])
        if last >= HIGH_PRICE_THRESHOLD:
            return HIGH_PRICE_CASH
    except Exception:
        pass
    return INIT_CASH


# ──────────── 数据获取 ────────────
_BS_LOGGED_IN = False


def _bs_login_once():
    global _BS_LOGGED_IN
    if not _BS_LOGGED_IN and HAS_BS:
        bs.login()
        _BS_LOGGED_IN = True


def _ymd_dash(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:]}" if len(s) == 8 else s


def fetch_one_bs(code: str, start: str, end: str) -> pd.DataFrame | None:
    if not HAS_BS:
        return None
    _bs_login_once()
    prefix = "sh" if code.startswith("6") else "sz"
    bs_code = f"{prefix}.{code}"
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,volume",
        start_date=_ymd_dash(start),
        end_date=_ymd_dash(end),
        frequency="d",
        adjustflag="2",
    )
    if rs.error_code != "0":
        return None
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[df["close"] > 0]  # 过滤停牌
    df = df.sort_values("date").reset_index(drop=True)
    return df


def fetch_one_ak(code: str, start: str, end: str, retry: int = 2) -> pd.DataFrame | None:
    if not HAS_AK:
        return None
    for _ in range(retry):
        try:
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=start, end_date=end, adjust="qfq",
            )
            if df is None or df.empty:
                return None
            col_map = {"日期": "date", "开盘": "open", "最高": "high",
                       "最低": "low", "收盘": "close", "成交量": "volume"}
            cols = [c for c in col_map if c in df.columns]
            df = df[cols].rename(columns=col_map)
            df["date"] = pd.to_datetime(df["date"])
            for c in ["open", "high", "low", "close", "volume"]:
                df[c] = df[c].astype(float)
            df = df.sort_values("date").reset_index(drop=True)
            return df
        except Exception:
            time.sleep(1.5)
    return None


def fetch_one(code: str, start: str, end: str) -> pd.DataFrame | None:
    """统一拉取入口：先 baostock，失败再 akshare"""
    df = fetch_one_bs(code, start, end)
    if df is not None and len(df) >= 60:
        return df
    return fetch_one_ak(code, start, end)


def update_universe_data(universe: dict, start: str, end: str) -> list[str]:
    """更新所有股票数据。返回成功的 code 列表"""
    print(f"\n=== 更新数据 ({start} ~ {end}) ===", flush=True)
    ok = []
    for code, name in universe.items():
        path = Path(DATA_DIR) / f"{code}.csv"
        df = fetch_one(code, start, end)
        if df is None or len(df) < 60:
            print(f"  ❌ {code} {name} 数据不足 ({len(df) if df is not None else 0} 条)", flush=True)
            continue
        df.to_csv(path, index=False)
        print(f"  ✓ {code} {name:<10} {len(df):>4} 条 → {path.name}", flush=True)
        ok.append(code)
        time.sleep(0.15)  # baostock 不需要重限速
    print(f"=== 数据完成：{len(ok)}/{len(universe)} ===\n", flush=True)
    if HAS_BS and _BS_LOGGED_IN:
        try:
            bs.logout()
        except Exception:
            pass
    return ok


# ──────────── A. 扩股票池矩阵 ────────────
def task_a_universe_matrix(codes: list[str]) -> list[dict]:
    print(f"\n{'='*80}\n A. 扩股票池矩阵：{len(codes)} 股 × {len(STRATEGIES)} 策略 = {len(codes)*len(STRATEGIES)} 次\n{'='*80}", flush=True)
    rows = []
    t0 = time.time()
    for code in codes:
        STOCK_NAMES.setdefault(code, EXPANDED_UNIVERSE.get(code, code))
        for strat in STRATEGIES:
            cash = _cash_for(code)
            ts = time.time()
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    r = run_backtest(code, strat, cash, verbose=False)
                rows.append(r)
                print(
                    f"  [{time.time()-ts:>5.1f}s] {code} {STOCK_NAMES[code]:<10} {strat:<14} "
                    f"收益 {r['total_return']:>+8.2f}%  夏普 {r['sharpe_ratio']:>+5.2f}  "
                    f"交易 {r['total_trades']:>3}  胜率 {r['win_rate']:>5.1f}%  本金¥{cash/10000:.0f}w",
                    flush=True,
                )
            except Exception as e:
                print(f"  ❌ {code} {strat}: {type(e).__name__}: {e}", flush=True)
    print(f" A. 完成，用时 {time.time()-t0:.1f}s\n", flush=True)
    return rows


def write_a_report(rows: list[dict]):
    out = OUT_ROOT / "A_universe_matrix.md"
    rows_sorted = sorted(rows, key=lambda x: -x["total_return"])
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# A. 扩股票池回测矩阵 ({len(rows)} 行)\n\n")
        f.write(f"- 股票数：{len({r['stock_code'] for r in rows})}\n")
        f.write(f"- 策略数：{len(STRATEGIES)}\n")
        f.write(f"- 初始资金：¥{INIT_CASH:,.0f}\n\n")

        f.write("## 🏆 总收益 Top 15\n\n| 排名 | 股票×策略 | 总收益 | 年化 | 回撤 | 夏普 | 交易 | 胜率 |\n|---|---|---:|---:|---:|---:|---:|---:|\n")
        for i, r in enumerate(rows_sorted[:15], 1):
            f.write(
                f"| {i} | {r['stock_code']} {r['stock_name']} × {r['strategy']} | "
                f"{r['total_return']:+.2f}% | {r['annual_return']:+.2f}% | "
                f"{r['max_drawdown']:.2f}% | {r['sharpe_ratio']:.2f} | "
                f"{r['total_trades']} | {r['win_rate']:.1f}% |\n"
            )

        # 策略平均
        f.write("\n## 各策略平均表现\n\n| 策略 | 平均收益 | 平均年化 | 平均回撤 | 平均夏普 | 平均交易 | 平均胜率 |\n|---|---:|---:|---:|---:|---:|---:|\n")
        by_strat = defaultdict(list)
        for r in rows:
            by_strat[r["strategy"]].append(r)
        for s, lst in by_strat.items():
            n = len(lst)
            avg = lambda k: sum(x[k] for x in lst) / n
            f.write(
                f"| {s} | {avg('total_return'):+.2f}% | {avg('annual_return'):+.2f}% | "
                f"{avg('max_drawdown'):.2f}% | {avg('sharpe_ratio'):.2f} | "
                f"{avg('total_trades'):.1f} | {avg('win_rate'):.1f}% |\n"
            )

        # 全量
        f.write("\n## 全量结果\n\n| 股票 | 策略 | 总收益 | 年化 | 回撤 | 夏普 | 交易 | 胜率 |\n|---|---|---:|---:|---:|---:|---:|---:|\n")
        for r in rows:
            f.write(
                f"| {r['stock_code']} {r['stock_name']} | {r['strategy']} | "
                f"{r['total_return']:+.2f}% | {r['annual_return']:+.2f}% | "
                f"{r['max_drawdown']:.2f}% | {r['sharpe_ratio']:.2f} | "
                f"{r['total_trades']} | {r['win_rate']:.1f}% |\n"
            )
    print(f"✅ A. 报告：{out}", flush=True)
    return out


# ──────────── B. MACD 参数扫描 ────────────
class MacdParamStrategy(bt.Strategy):
    """与 macd_strategy.py 一致，仅参数化"""
    params = (
        ("fast_period", 12),
        ("slow_period", 26),
        ("signal_period", 9),
        ("position_pct", 0.50),
    )

    def __init__(self):
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.fast_period,
            period_me2=self.p.slow_period,
            period_signal=self.p.signal_period,
        )
        self.crossover = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)
        self.order = None

    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None

    def next(self):
        if self.order:
            return
        if not self.position:
            if self.crossover > 0:
                cash = self.broker.getcash() * self.p.position_pct
                size = (int(cash / self.data.close[0]) // 100) * 100
                if size > 0:
                    self.order = self.buy(size=size)
        else:
            if self.crossover < 0:
                self.order = self.sell(size=self.position.size)


def run_param_backtest(code: str, fast: int, slow: int, signal: int) -> dict:
    csv_path = Path(DATA_DIR) / f"{code}.csv"
    cash = _cash_for(code)
    cerebro = bt.Cerebro()
    data = bt.feeds.GenericCSVData(
        dataname=str(csv_path), dtformat="%Y-%m-%d",
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1, headers=True,
    )
    cerebro.adddata(data)
    cerebro.addstrategy(MacdParamStrategy, fast_period=fast, slow_period=slow, signal_period=signal)
    cerebro.broker.setcash(cash)
    cerebro.broker.addcommissioninfo(StampDutyCommission())
    cerebro.addanalyzer(btanalyzers.SharpeRatio, _name="sharpe", riskfreerate=0.03, annualize=True)
    cerebro.addanalyzer(btanalyzers.DrawDown, _name="dd")
    cerebro.addanalyzer(btanalyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(btanalyzers.TimeReturn, _name="tr")

    sv = cerebro.broker.getvalue()
    res = cerebro.run()
    ev = cerebro.broker.getvalue()
    s = res[0]
    tr = s.analyzers.tr.get_analysis()
    dd = s.analyzers.dd.get_analysis()
    tra = s.analyzers.trades.get_analysis()
    sr = s.analyzers.sharpe.get_analysis().get("sharperatio") or 0.0
    n_days = len(tr) or 1
    n_years = n_days / 252.0
    annual = ((ev / sv) ** (1 / max(n_years, 0.01)) - 1) * 100
    won = tra.get("won", {}).get("total", 0)
    lost = tra.get("lost", {}).get("total", 0)
    closed = won + lost
    return {
        "fast": fast, "slow": slow, "signal": signal,
        "total_return": (ev - sv) / sv * 100,
        "annual_return": annual,
        "max_drawdown": dd.max.drawdown if dd.max.drawdown else 0,
        "sharpe": sr,
        "trades": tra.get("total", {}).get("total", 0),
        "win_rate": (won / closed * 100) if closed else 0,
    }


def task_b_macd_grid(codes: list[str]) -> dict:
    """对 5 只代表股做 MACD 网格扫描"""
    # 选 5 只代表性的：包括昨晚 MACD 表现好的 + 新加的龙头
    grid_codes = [c for c in ["600330", "000967", "002256", "600519", "300750"] if c in codes]

    fast_list = [8, 12, 16]
    slow_list = [21, 26, 30]
    signal_list = [6, 9, 12]
    combos = [(f, s, sig) for f, s, sig in itertools.product(fast_list, slow_list, signal_list) if f < s]
    print(f"\n{'='*80}\n B. MACD 参数扫描：{len(grid_codes)} 股 × {len(combos)} 组 = {len(grid_codes)*len(combos)} 次\n{'='*80}", flush=True)

    results = {}
    t0 = time.time()
    for code in grid_codes:
        print(f"\n--- {code} {STOCK_NAMES.get(code, '')} ---", flush=True)
        rs = []
        for f, s, sig in combos:
            try:
                r = run_param_backtest(code, f, s, sig)
                rs.append(r)
            except Exception as e:
                print(f"   ❌ ({f},{s},{sig}): {e}", flush=True)
        rs_sorted = sorted(rs, key=lambda x: -x["total_return"])
        for i, r in enumerate(rs_sorted[:3]):
            print(f"  Top{i+1}: ({r['fast']},{r['slow']},{r['signal']})  收益 {r['total_return']:+.2f}%  夏普 {r['sharpe']:+.2f}  交易 {r['trades']}", flush=True)
        results[code] = rs
    print(f"\n B. 完成，用时 {time.time()-t0:.1f}s\n", flush=True)
    return results


def write_b_report(results: dict):
    out = OUT_ROOT / "B_macd_gridsearch.md"
    with out.open("w", encoding="utf-8") as f:
        f.write("# B. MACD 参数扫描\n\n")
        f.write("- 默认参数：(12, 26, 9)\n")
        f.write("- 扫描组合：fast ∈ {8,12,16}, slow ∈ {21,26,30}, signal ∈ {6,9,12}\n")
        f.write("- 约束：fast < slow，共 ~27 组（按是否满足约束）\n\n")
        for code, rs in results.items():
            name = STOCK_NAMES.get(code, code)
            rs_sorted = sorted(rs, key=lambda x: -x["total_return"])
            default = next((r for r in rs if (r["fast"], r["slow"], r["signal"]) == (12, 26, 9)), None)
            f.write(f"## {code} {name}\n\n")
            if default:
                f.write(f"**默认 (12,26,9)**：收益 {default['total_return']:+.2f}%  夏普 {default['sharpe']:+.2f}  交易 {default['trades']}  胜率 {default['win_rate']:.1f}%\n\n")
            f.write("| 排名 | 参数 (f,s,sig) | 总收益 | 年化 | 回撤 | 夏普 | 交易 | 胜率 |\n|---|---|---:|---:|---:|---:|---:|---:|\n")
            for i, r in enumerate(rs_sorted[:8], 1):
                tag = " 🌟" if (r["fast"], r["slow"], r["signal"]) == (12, 26, 9) else ""
                f.write(
                    f"| {i} | ({r['fast']},{r['slow']},{r['signal']}){tag} | "
                    f"{r['total_return']:+.2f}% | {r['annual_return']:+.2f}% | "
                    f"{r['max_drawdown']:.2f}% | {r['sharpe']:+.2f} | "
                    f"{r['trades']} | {r['win_rate']:.1f}% |\n"
                )
            # 最差 3 个
            f.write("\n**最差 3 组**：\n\n")
            for r in rs_sorted[-3:]:
                f.write(f"- ({r['fast']},{r['slow']},{r['signal']})  收益 {r['total_return']:+.2f}%\n")
            f.write("\n")
    print(f"✅ B. 报告：{out}", flush=True)
    return out


# ──────────── C. Walk-forward / out-of-sample ────────────
def split_csv_in_out(code: str, ratio: float = 0.7) -> tuple[Path, Path]:
    """按时间切分 CSV，返回 (in_sample.csv, out_sample.csv)"""
    src = Path(DATA_DIR) / f"{code}.csv"
    df = pd.read_csv(src)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    n = len(df)
    cut = int(n * ratio)
    in_path = OUT_ROOT / "tmp_data" / f"{code}_in.csv"
    out_path = OUT_ROOT / "tmp_data" / f"{code}_out.csv"
    in_path.parent.mkdir(parents=True, exist_ok=True)
    df.iloc[:cut].to_csv(in_path, index=False)
    df.iloc[cut:].to_csv(out_path, index=False)
    return in_path, out_path


def run_backtest_with_path(csv_path: Path, strategy_name: str, cash: float = INIT_CASH) -> dict:
    """跑回测但数据用指定路径（用于切分后的样本）"""
    from backtest import load_strategy
    strat_cls, disp = load_strategy(strategy_name)
    cerebro = bt.Cerebro()
    data = bt.feeds.GenericCSVData(
        dataname=str(csv_path), dtformat="%Y-%m-%d",
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1, headers=True,
    )
    cerebro.adddata(data)
    kw = {}
    if strategy_name in ("composite", "composite_v2"):
        kw["printlog"] = False
    cerebro.addstrategy(strat_cls, **kw)
    cerebro.broker.setcash(cash)
    cerebro.broker.addcommissioninfo(StampDutyCommission())
    cerebro.addanalyzer(btanalyzers.SharpeRatio, _name="sharpe", riskfreerate=0.03, annualize=True)
    cerebro.addanalyzer(btanalyzers.DrawDown, _name="dd")
    cerebro.addanalyzer(btanalyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(btanalyzers.TimeReturn, _name="tr")
    if strategy_name not in ("composite", "composite_v2"):
        cerebro.addsizer(bt.sizers.FixedSize, stake=100)
    sv = cerebro.broker.getvalue()
    res = cerebro.run()
    ev = cerebro.broker.getvalue()
    s = res[0]
    tr = s.analyzers.tr.get_analysis()
    dd = s.analyzers.dd.get_analysis()
    tra = s.analyzers.trades.get_analysis()
    sr = s.analyzers.sharpe.get_analysis().get("sharperatio") or 0.0
    n_days = len(tr) or 1
    n_years = n_days / 252.0
    annual = ((ev / sv) ** (1 / max(n_years, 0.01)) - 1) * 100
    won = tra.get("won", {}).get("total", 0)
    lost = tra.get("lost", {}).get("total", 0)
    closed = won + lost
    return {
        "total_return": (ev - sv) / sv * 100,
        "annual_return": annual,
        "max_drawdown": dd.max.drawdown if dd.max.drawdown else 0,
        "sharpe": sr,
        "trades": tra.get("total", {}).get("total", 0),
        "win_rate": (won / closed * 100) if closed else 0,
    }


def task_c_walkforward(codes: list[str]) -> list[dict]:
    """对原 4 只做 70/30 切分，跑全策略对比"""
    sub = [c for c in ["000967", "002256", "002453", "600330", "600519", "300750"] if c in codes]
    print(f"\n{'='*80}\n C. Walk-forward (70% in / 30% out)：{len(sub)} 股 × {len(STRATEGIES)} 策略\n{'='*80}", flush=True)
    rows = []
    t0 = time.time()
    for code in sub:
        try:
            in_p, out_p = split_csv_in_out(code, ratio=0.7)
        except Exception as e:
            print(f"  ❌ {code} 切分失败：{e}", flush=True)
            continue
        for strat in STRATEGIES:
            cash = _cash_for(code)
            try:
                r_in = run_backtest_with_path(in_p, strat, cash=cash)
                r_out = run_backtest_with_path(out_p, strat, cash=cash)
                row = {
                    "code": code, "name": STOCK_NAMES.get(code, code), "strategy": strat,
                    "in_total": r_in["total_return"], "in_annual": r_in["annual_return"],
                    "in_sharpe": r_in["sharpe"], "in_trades": r_in["trades"],
                    "out_total": r_out["total_return"], "out_annual": r_out["annual_return"],
                    "out_sharpe": r_out["sharpe"], "out_trades": r_out["trades"],
                }
                row["degradation"] = r_in["annual_return"] - r_out["annual_return"]
                rows.append(row)
                print(
                    f"  {code} {STOCK_NAMES.get(code,'')[:6]:<6} {strat:<14} "
                    f"IN 年化 {r_in['annual_return']:>+7.2f}% | OUT 年化 {r_out['annual_return']:>+7.2f}% | "
                    f"衰减 {row['degradation']:>+6.2f}pp",
                    flush=True,
                )
            except Exception as e:
                print(f"  ❌ {code} {strat}: {e}", flush=True)
    print(f"\n C. 完成，用时 {time.time()-t0:.1f}s\n", flush=True)
    return rows


def write_c_report(rows: list[dict]):
    out = OUT_ROOT / "C_walkforward.md"
    with out.open("w", encoding="utf-8") as f:
        f.write("# C. Walk-forward / Out-of-sample 检验\n\n")
        f.write("- 切分：前 70% 历史作 In-sample (训练/参考)，后 30% 作 Out-of-sample (检验)\n")
        f.write("- 关键指标：**衰减 (degradation)** = IN 年化 − OUT 年化，越小越鲁棒；负值=样本外更好\n\n")
        f.write("| 股票 | 策略 | IN 年化 | OUT 年化 | 衰减 (pp) | IN 夏普 | OUT 夏普 | IN 交易 | OUT 交易 |\n")
        f.write("|---|---|---:|---:|---:|---:|---:|---:|---:|\n")
        rows_sorted = sorted(rows, key=lambda x: x["degradation"])
        for r in rows_sorted:
            tag = ""
            if r["degradation"] < 5: tag = " ✅"
            elif r["degradation"] > 30: tag = " ⚠️"
            f.write(
                f"| {r['code']} {r['name']} | {r['strategy']} | "
                f"{r['in_annual']:+.2f}% | {r['out_annual']:+.2f}% | "
                f"{r['degradation']:+.2f}{tag} | {r['in_sharpe']:+.2f} | {r['out_sharpe']:+.2f} | "
                f"{r['in_trades']} | {r['out_trades']} |\n"
            )

        # 策略稳健榜
        by_strat = defaultdict(list)
        for r in rows:
            by_strat[r["strategy"]].append(r["degradation"])
        f.write("\n## 各策略平均衰减 (pp)\n\n| 策略 | 平均衰减 | 样本数 |\n|---|---:|---:|\n")
        for s, ds in sorted(by_strat.items(), key=lambda x: sum(x[1])/len(x[1])):
            f.write(f"| {s} | {sum(ds)/len(ds):+.2f} | {len(ds)} |\n")

        f.write("\n## 解读速记\n\n- 衰减 ≤ 5pp：策略稳健，样本外表现接近样本内 ✅\n")
        f.write("- 衰减 5~30pp：可用，但需打折扣\n- 衰减 > 30pp：疑似过拟合 ⚠️\n")
        f.write("- 衰减为负：样本外**更好**，可能遇到顺风期，谨慎对待\n")
    print(f"✅ C. 报告：{out}", flush=True)
    return out


# ──────────── D. 新策略：量价突破 ────────────
class VolumeBreakoutStrategy(bt.Strategy):
    """
    量价突破：
    - 收盘 > 20 日新高 AND 成交量 > 5 日均量 * 1.5  → 买入 (50% 仓位)
    - 收盘 < 10 日均线 OR 累计跌幅 > 8%  → 卖出
    """
    params = (
        ("breakout_period", 20),
        ("vol_avg_period", 5),
        ("vol_mult", 1.5),
        ("ma_exit_period", 10),
        ("stop_loss", 0.08),
        ("position_pct", 0.50),
    )

    def __init__(self):
        self.high20 = bt.indicators.Highest(self.data.close, period=self.p.breakout_period)
        self.vol_avg = bt.indicators.SMA(self.data.volume, period=self.p.vol_avg_period)
        self.ma_exit = bt.indicators.SMA(self.data.close, period=self.p.ma_exit_period)
        self.order = None
        self.entry_price = None

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.entry_price = order.executed.price
            else:
                self.entry_price = None
        self.order = None

    def next(self):
        if self.order:
            return
        if not self.position:
            # 突破前 20 日新高 + 放量
            prev_high = self.high20[-1]  # 不含今日
            if (self.data.close[0] > prev_high
                    and self.data.volume[0] > self.vol_avg[0] * self.p.vol_mult):
                cash = self.broker.getcash() * self.p.position_pct
                size = (int(cash / self.data.close[0]) // 100) * 100
                if size > 0:
                    self.order = self.buy(size=size)
        else:
            # 跌破 10 日均线或累计跌幅过大
            if self.entry_price:
                drop = (self.data.close[0] - self.entry_price) / self.entry_price
                if drop < -self.p.stop_loss:
                    self.order = self.sell(size=self.position.size)
                    return
            if self.data.close[0] < self.ma_exit[0]:
                self.order = self.sell(size=self.position.size)


def task_d_new_strategy(codes: list[str]) -> list[dict]:
    """量价突破策略 vs MACD 对比"""
    # 取 12 只代表股票
    sub = codes[:12]
    print(f"\n{'='*80}\n D. 新策略：量价突破，对 {len(sub)} 股回测\n{'='*80}", flush=True)
    rows = []
    t0 = time.time()
    for code in sub:
        csv_path = Path(DATA_DIR) / f"{code}.csv"
        if not csv_path.exists():
            continue
        # 量价突破
        try:
            cash = _cash_for(code)
            cerebro = bt.Cerebro()
            data = bt.feeds.GenericCSVData(
                dataname=str(csv_path), dtformat="%Y-%m-%d",
                datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1, headers=True,
            )
            cerebro.adddata(data)
            cerebro.addstrategy(VolumeBreakoutStrategy)
            cerebro.broker.setcash(cash)
            cerebro.broker.addcommissioninfo(StampDutyCommission())
            cerebro.addanalyzer(btanalyzers.SharpeRatio, _name="sharpe", riskfreerate=0.03, annualize=True)
            cerebro.addanalyzer(btanalyzers.DrawDown, _name="dd")
            cerebro.addanalyzer(btanalyzers.TradeAnalyzer, _name="trades")
            cerebro.addanalyzer(btanalyzers.TimeReturn, _name="tr")
            sv = cerebro.broker.getvalue()
            res = cerebro.run()
            ev = cerebro.broker.getvalue()
            s = res[0]
            tr = s.analyzers.tr.get_analysis()
            dd = s.analyzers.dd.get_analysis()
            tra = s.analyzers.trades.get_analysis()
            sr = s.analyzers.sharpe.get_analysis().get("sharperatio") or 0.0
            n_years = len(tr) / 252.0 if tr else 0.01
            annual = ((ev / sv) ** (1 / max(n_years, 0.01)) - 1) * 100
            won = tra.get("won", {}).get("total", 0)
            lost = tra.get("lost", {}).get("total", 0)
            closed = won + lost
            row = {
                "code": code, "name": STOCK_NAMES.get(code, code),
                "total_return": (ev - sv) / sv * 100,
                "annual_return": annual,
                "max_drawdown": dd.max.drawdown if dd.max.drawdown else 0,
                "sharpe": sr,
                "trades": tra.get("total", {}).get("total", 0),
                "win_rate": (won / closed * 100) if closed else 0,
                "cash": cash,
            }
            rows.append(row)
            print(
                f"  {code} {STOCK_NAMES.get(code,'')[:6]:<6}  "
                f"收益 {row['total_return']:>+8.2f}%  年化 {row['annual_return']:>+7.2f}%  "
                f"夏普 {row['sharpe']:>+5.2f}  交易 {row['trades']:>3}  胜率 {row['win_rate']:>5.1f}%",
                flush=True,
            )
        except Exception as e:
            print(f"  ❌ {code}: {type(e).__name__}: {e}", flush=True)
    print(f"\n D. 完成，用时 {time.time()-t0:.1f}s\n", flush=True)
    return rows


def write_d_report(rows: list[dict]):
    out = OUT_ROOT / "D_new_strategy.md"
    with out.open("w", encoding="utf-8") as f:
        f.write("# D. 新策略：量价突破 (Volume Breakout)\n\n")
        f.write("**逻辑**：\n- **入场**：收盘 > 前 20 日最高价 AND 成交量 > 5 日均量 × 1.5（突破伴随放量）\n")
        f.write("- **出场**：累计亏损 > 8% 止损 OR 收盘跌破 10 日均线\n")
        f.write("- **仓位**：50% 现金\n\n")
        rows_sorted = sorted(rows, key=lambda x: -x["total_return"])
        f.write("## 全量结果\n\n| 股票 | 总收益 | 年化 | 回撤 | 夏普 | 交易 | 胜率 |\n|---|---:|---:|---:|---:|---:|---:|\n")
        for r in rows_sorted:
            f.write(
                f"| {r['code']} {r['name']} | {r['total_return']:+.2f}% | {r['annual_return']:+.2f}% | "
                f"{r['max_drawdown']:.2f}% | {r['sharpe']:+.2f} | {r['trades']} | {r['win_rate']:.1f}% |\n"
            )
        if rows:
            avg = lambda k: sum(x[k] for x in rows) / len(rows)
            f.write(f"\n**平均**：收益 {avg('total_return'):+.2f}%，年化 {avg('annual_return'):+.2f}%，夏普 {avg('sharpe'):+.2f}，胜率 {avg('win_rate'):.1f}%\n")
    print(f"✅ D. 报告：{out}", flush=True)
    return out


# ──────────── 综合 summary ────────────
def write_summary(a_rows, b_results, c_rows, d_rows):
    out = OUT_ROOT / "summary.md"
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# 周末扩展回测综合周报 2026-05-24\n\n")
        f.write(f"运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"## 任务清单\n\n")
        f.write(f"- ✅ **A. 扩股票池**：{len({r['stock_code'] for r in a_rows})} 只 × {len(STRATEGIES)} 策略 = {len(a_rows)} 次回测\n")
        f.write(f"- ✅ **B. MACD 参数扫描**：{len(b_results)} 只代表股，每只 ~27 组参数\n")
        f.write(f"- ✅ **C. Walk-forward 检验**：{len({r['code'] for r in c_rows})} 只 × {len(STRATEGIES)} 策略\n")
        f.write(f"- ✅ **D. 新策略**：量价突破 {len(d_rows)} 只\n\n")

        # A: 全局 Top
        a_top = sorted(a_rows, key=lambda x: -x["total_return"])[:5]
        f.write(f"## 🏆 A. 扩样本 Top 5\n\n| 股票×策略 | 总收益 | 年化 | 夏普 |\n|---|---:|---:|---:|\n")
        for r in a_top:
            f.write(f"| {r['stock_code']} {r['stock_name']} × {r['strategy']} | {r['total_return']:+.2f}% | {r['annual_return']:+.2f}% | {r['sharpe_ratio']:.2f} |\n")

        # A: 各策略胜率（赢公允度）
        by_strat = defaultdict(list)
        for r in a_rows:
            by_strat[r["strategy"]].append(r)
        f.write(f"\n## 各策略大样本平均\n\n| 策略 | 平均收益 | 平均夏普 | 中位数收益 | 正收益占比 |\n|---|---:|---:|---:|---:|\n")
        for s, lst in by_strat.items():
            n = len(lst)
            ret = sorted([r["total_return"] for r in lst])
            avg = sum(ret) / n
            med = ret[n // 2]
            pos = sum(1 for x in ret if x > 0) / n * 100
            avg_sr = sum(r["sharpe_ratio"] for r in lst) / n
            f.write(f"| {s} | {avg:+.2f}% | {avg_sr:+.2f} | {med:+.2f}% | {pos:.0f}% |\n")

        # B: 每股最优参数
        f.write(f"\n## B. MACD 各股最优参数\n\n| 股票 | 最优 (f,s,sig) | 最优收益 | 默认 (12,26,9) | 提升 |\n|---|---|---:|---:|---:|\n")
        for code, rs in b_results.items():
            if not rs: continue
            best = max(rs, key=lambda x: x["total_return"])
            default = next((r for r in rs if (r["fast"], r["slow"], r["signal"]) == (12, 26, 9)), None)
            d_ret = default["total_return"] if default else 0
            improve = best["total_return"] - d_ret
            f.write(f"| {code} {STOCK_NAMES.get(code,'')} | ({best['fast']},{best['slow']},{best['signal']}) | {best['total_return']:+.2f}% | {d_ret:+.2f}% | {improve:+.2f}pp |\n")

        # C: 衰减榜
        f.write(f"\n## C. Walk-forward 最稳健 (衰减小) Top 5\n\n| 股票 | 策略 | IN 年化 | OUT 年化 | 衰减 (pp) |\n|---|---|---:|---:|---:|\n")
        c_sorted = sorted(c_rows, key=lambda x: x["degradation"])
        for r in c_sorted[:5]:
            f.write(f"| {r['code']} {r['name']} | {r['strategy']} | {r['in_annual']:+.2f}% | {r['out_annual']:+.2f}% | {r['degradation']:+.2f} |\n")
        f.write(f"\n**最易过拟合 Top 3**：\n\n")
        for r in c_sorted[-3:]:
            f.write(f"- {r['code']} {r['name']} × {r['strategy']}：衰减 {r['degradation']:+.2f}pp\n")

        # D: 新策略
        if d_rows:
            d_avg_total = sum(r["total_return"] for r in d_rows) / len(d_rows)
            d_avg_sharpe = sum(r["sharpe"] for r in d_rows) / len(d_rows)
            f.write(f"\n## D. 量价突破策略\n\n- 平均收益 **{d_avg_total:+.2f}%**\n- 平均夏普 **{d_avg_sharpe:+.2f}**\n- 已纳入下一轮策略候选\n")

        f.write(f"\n## 详见\n\n- [A_universe_matrix.md](A_universe_matrix.md)\n- [B_macd_gridsearch.md](B_macd_gridsearch.md)\n- [C_walkforward.md](C_walkforward.md)\n- [D_new_strategy.md](D_new_strategy.md)\n")
    print(f"\n📋 综合周报：{out}", flush=True)


# ──────────── 入口 ────────────
def main():
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=730)).strftime("%Y%m%d")

    print("\n" + "█" * 80)
    print(f" 周末扩展回测 2026-05-24  ({start} ~ {end})")
    print("█" * 80)

    # 1. 数据更新
    ok = update_universe_data(EXPANDED_UNIVERSE, start, end)
    if len(ok) < 4:
        print("❌ 可用股票太少，终止", flush=True)
        return

    # 2. 各任务
    a_rows = task_a_universe_matrix(ok)
    write_a_report(a_rows)

    b_results = task_b_macd_grid(ok)
    write_b_report(b_results)

    c_rows = task_c_walkforward(ok)
    write_c_report(c_rows)

    d_rows = task_d_new_strategy(ok)
    write_d_report(d_rows)

    write_summary(a_rows, b_results, c_rows, d_rows)

    print(f"\n{'█'*80}\n 全部完成！查看 {OUT_ROOT}\n{'█'*80}\n", flush=True)


if __name__ == "__main__":
    main()
