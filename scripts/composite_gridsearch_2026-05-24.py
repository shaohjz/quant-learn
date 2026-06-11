"""F: 复合策略参数扫描

对 E2 严格筛选出来的 4 只 A 档股票 + 上下文里出现过的稳健股票
做复合策略的核心参数 grid search。

扫描参数（5 维）：
  - buy_signals_required: 2/3/4
  - sell_signals_required: 1/2/3
  - position_pct: 0.4/0.6/0.8
  - stop_loss_pct: 0.05/0.08/0.12
  - trailing_profit_threshold: 0.10/0.20/0.30

每股 243 组合。同时跑 walk-forward (70/30) 验证鲁棒性。

输出：
  output/weekly_full_2026-05-24/F_composite_gridsearch.md
"""
from __future__ import annotations
import sys, time, importlib.util, itertools, warnings
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

import matplotlib; matplotlib.use("Agg")
import backtrader as bt
import backtrader.analyzers as btanalyzers
bt.Cerebro.plot = lambda self, *a, **k: [[None]]

# 复用主脚本的工具
spec = importlib.util.spec_from_file_location("w", ROOT / "scripts" / "weekend_full_2026-05-24.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

from backtest import STOCK_NAMES, StampDutyCommission
STOCK_NAMES.update(m.EXPANDED_UNIVERSE)

from strategies.composite_strategy import CompositeStrategy

OUT_DIR = ROOT / "output" / "weekly_full_2026-05-24"

# 选股票池：A 档 4 只 + B 档值得观察的几只
SCAN_CODES = ["000967", "002920", "600703", "002256",  # E2 A 档
              "002453", "600330", "300059", "603290",  # 复合策略表现好的额外候选
              "300124", "002475"]                       # B 档亮点
INIT_CASH_DEFAULT = 100_000.0
INIT_CASH_HIGH = 500_000.0


def _cash_for(code):
    import pandas as pd
    try:
        df = pd.read_csv(Path(m.DATA_DIR) / f"{code}.csv")
        if float(df["close"].iloc[-1]) >= 100:
            return INIT_CASH_HIGH
    except Exception:
        pass
    return INIT_CASH_DEFAULT


# 参数网格
GRID = {
    "buy_signals_required": [2, 3, 4],
    "sell_signals_required": [1, 2, 3],
    "position_pct": [0.4, 0.6, 0.8],
    "stop_loss_pct": [0.05, 0.08, 0.12],
    "trailing_profit_threshold": [0.10, 0.20, 0.30],
}
DEFAULT_PARAMS = {
    "buy_signals_required": 3, "sell_signals_required": 2,
    "position_pct": 0.60, "stop_loss_pct": 0.08,
    "trailing_profit_threshold": 0.20,
}


def all_combos():
    keys = list(GRID.keys())
    for vals in itertools.product(*[GRID[k] for k in keys]):
        yield dict(zip(keys, vals))


def run_one(csv_path: Path, params: dict, cash: float) -> dict:
    cerebro = bt.Cerebro()
    data = bt.feeds.GenericCSVData(
        dataname=str(csv_path), dtformat="%Y-%m-%d",
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1, headers=True,
    )
    cerebro.adddata(data)
    cerebro.addstrategy(CompositeStrategy, printlog=False, **params)
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
    n_years = max(len(tr) / 252.0, 0.01)
    return {
        "total_return": (ev - sv) / sv * 100,
        "annual_return": ((ev / sv) ** (1 / n_years) - 1) * 100,
        "max_drawdown": dd.max.drawdown if dd.max.drawdown else 0,
        "sharpe": sr,
        "trades": tra.get("total", {}).get("total", 0),
    }


def main():
    codes = [c for c in SCAN_CODES if (Path(m.DATA_DIR) / f"{c}.csv").exists()]
    combos = list(all_combos())
    print(f"\n{'='*80}")
    print(f" F. 复合策略参数扫描")
    print(f" 股票数：{len(codes)} | 参数组合：{len(combos)} | 总次数：{len(codes)*len(combos)*2} (含 IN/OUT)")
    print(f"{'='*80}\n", flush=True)

    all_results = {}  # code -> [{params, full, in, out, deg}, ...]
    t0 = time.time()
    for ci, code in enumerate(codes, 1):
        cash = _cash_for(code)
        # 切分 in/out
        in_p, out_p = m.split_csv_in_out(code, ratio=0.7)
        full_p = Path(m.DATA_DIR) / f"{code}.csv"

        rs = []
        ts = time.time()
        for pi, params in enumerate(combos):
            try:
                r_full = run_one(full_p, params, cash)
                r_in = run_one(in_p, params, cash)
                r_out = run_one(out_p, params, cash)
                rs.append({
                    "params": params,
                    "full": r_full,
                    "in": r_in,
                    "out": r_out,
                    "deg": r_in["annual_return"] - r_out["annual_return"],
                })
            except Exception as e:
                pass
        elapsed = time.time() - ts
        # 找最优（按 OUT 年化）
        rs_sorted = sorted(rs, key=lambda x: -x["out"]["annual_return"])
        if rs_sorted:
            best = rs_sorted[0]
            print(f"  [{ci}/{len(codes)}] {code} {STOCK_NAMES.get(code,'')[:6]:<6} {len(rs)} 组 用时 {elapsed:.1f}s",
                  flush=True)
            print(f"      Top1 OUT 年化 {best['out']['annual_return']:+7.2f}%  夏普 {best['out']['sharpe']:+5.2f}  "
                  f"参数 {best['params']}", flush=True)
        all_results[code] = rs
    print(f"\n F. 完成，总用时 {time.time()-t0:.1f}s\n", flush=True)

    write_report(all_results, codes)


def write_report(all_results: dict, codes: list[str]):
    out = OUT_DIR / "F_composite_gridsearch.md"
    n_combos = len(list(all_combos()))
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# F. 复合策略参数扫描\n\n")
        f.write(f"- 股票池：{len(codes)} 只（含 E2 A 档 4 只 + 复合策略表现好的额外候选）\n")
        f.write(f"- 参数空间：{n_combos} 组（5 维网格）\n")
        f.write(f"- 每组都跑 IN/OUT/Full 三次（共 {len(codes)*n_combos*3} 次回测）\n\n")

        f.write("## 参数网格\n\n")
        f.write("| 参数 | 默认 | 候选 |\n|---|---|---|\n")
        for k, vals in GRID.items():
            f.write(f"| {k} | {DEFAULT_PARAMS[k]} | {vals} |\n")

        # 默认参数下各股表现
        f.write("\n## 默认参数 (3,2,0.6,0.08,0.20) 各股 OUT 表现\n\n")
        f.write("| 股票 | Full 收益 | OUT 年化 | OUT 夏普 | OUT 交易 | 衰减 |\n|---|---:|---:|---:|---:|---:|\n")
        for code in codes:
            rs = all_results.get(code, [])
            d = next((r for r in rs if r["params"] == DEFAULT_PARAMS), None)
            if d:
                f.write(f"| {code} {STOCK_NAMES.get(code,'')} | "
                        f"{d['full']['total_return']:+.2f}% | {d['out']['annual_return']:+.2f}% | "
                        f"{d['out']['sharpe']:+.2f} | {d['out']['trades']} | {d['deg']:+.2f}pp |\n")

        # 每股最优
        f.write("\n## 每股最优参数（按 OUT 年化排序，仅取 OUT 真正赚钱的）\n\n")
        for code in codes:
            rs = all_results.get(code, [])
            # 严格鲁棒筛选：OUT > 0 + |衰减| ≤ 15
            robust = [r for r in rs
                      if r["out"]["annual_return"] > 0
                      and abs(r["deg"]) <= 15
                      and r["out"]["trades"] >= 2]
            robust.sort(key=lambda x: -x["out"]["annual_return"])
            name = STOCK_NAMES.get(code, code)
            f.write(f"\n### {code} {name}（{len(robust)} 组通过鲁棒筛选）\n\n")
            if not robust:
                f.write("(无通过鲁棒筛选的参数组)\n")
                continue
            f.write("| 排名 | 参数 (b_req, s_req, pos%, stop%, trail%) | OUT 年化 | OUT 夏普 | OUT 交易 | 衰减 |\n")
            f.write("|---|---|---:|---:|---:|---:|\n")
            for i, r in enumerate(robust[:5], 1):
                p = r["params"]
                tag = " 🌟默认" if p == DEFAULT_PARAMS else ""
                f.write(
                    f"| {i} | ({p['buy_signals_required']},{p['sell_signals_required']},"
                    f"{int(p['position_pct']*100)},{int(p['stop_loss_pct']*100)},{int(p['trailing_profit_threshold']*100)}){tag} | "
                    f"{r['out']['annual_return']:+.2f}% | {r['out']['sharpe']:+.2f} | "
                    f"{r['out']['trades']} | {r['deg']:+.2f}pp |\n"
                )

        # 各参数维度的边际效应
        f.write("\n\n## 各参数维度的边际效应\n\n")
        f.write("将所有股票×所有组合的 OUT 年化按单个参数分组求平均。\n\n")
        # 把所有 r 平铺
        flat = [(code, r) for code, rs in all_results.items() for r in rs]
        for k in GRID:
            f.write(f"\n### `{k}`（默认 {DEFAULT_PARAMS[k]}）\n\n")
            by_v = defaultdict(list)
            for _, r in flat:
                by_v[r["params"][k]].append(r["out"]["annual_return"])
            f.write("| 取值 | 平均 OUT 年化 | 中位数 | 正收益占比 |\n|---|---:|---:|---:|\n")
            for v in sorted(by_v):
                arr = sorted(by_v[v])
                avg = sum(arr) / len(arr)
                med = arr[len(arr) // 2]
                pos = sum(1 for x in arr if x > 0) / len(arr) * 100
                tag = " 🌟默认" if v == DEFAULT_PARAMS[k] else ""
                f.write(f"| {v}{tag} | {avg:+.2f}% | {med:+.2f}% | {pos:.0f}% |\n")

        # 全股票通用最优（在所有股票上都不算差的参数）
        f.write("\n\n## 「全股通用」鲁棒参数 Top 5\n\n")
        f.write("策略：对每组参数，在 N 只股票上的 OUT 年化取 **平均**和**中位数**，\n")
        f.write("再按「中位数 OUT 年化 - |衰减|」综合打分排序。\n\n")
        agg = defaultdict(list)
        for code, rs in all_results.items():
            for r in rs:
                key = tuple(sorted(r["params"].items()))
                agg[key].append((r["out"]["annual_return"], r["deg"]))
        scored = []
        for key, lst in agg.items():
            outs = [x[0] for x in lst]
            degs = [abs(x[1]) for x in lst]
            outs_s = sorted(outs)
            med_out = outs_s[len(outs_s) // 2]
            avg_out = sum(outs) / len(outs)
            med_deg = sorted(degs)[len(degs) // 2]
            score = med_out - med_deg * 0.3  # 衰减 30% 罚分
            scored.append((dict(key), avg_out, med_out, med_deg, score))
        scored.sort(key=lambda x: -x[4])
        f.write("| 排名 | 参数 | 平均 OUT 年化 | 中位数 OUT 年化 | 中位数 |衰减| | 综合分 |\n|---|---|---:|---:|---:|---:|\n")
        for i, (params, avg, med, mdeg, sc) in enumerate(scored[:10], 1):
            tag = " 🌟" if params == DEFAULT_PARAMS else ""
            f.write(
                f"| {i} | (b={params['buy_signals_required']},s={params['sell_signals_required']},"
                f"pos={params['position_pct']},sl={params['stop_loss_pct']},"
                f"tp={params['trailing_profit_threshold']}){tag} | "
                f"{avg:+.2f}% | {med:+.2f}% | {mdeg:.2f} | {sc:+.2f} |\n"
            )

        # 默认参数排名
        default_key = tuple(sorted(DEFAULT_PARAMS.items()))
        for i, (params, *_) in enumerate(scored, 1):
            if params == DEFAULT_PARAMS:
                f.write(f"\n**默认参数综合分排名：{i}/{len(scored)}**\n")
                break

    print(f"📋 报告：{out}", flush=True)


if __name__ == "__main__":
    main()
