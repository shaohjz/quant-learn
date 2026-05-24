"""C-FULL: 全 31 股 × 5 策略 walk-forward 检验

补充上午跑过的 6 股 walk-forward，扩展到全部股票池。
"""
from __future__ import annotations
import sys, os, time, importlib.util
import warnings
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

import matplotlib; matplotlib.use("Agg")
import backtrader as bt
bt.Cerebro.plot = lambda self, *a, **k: [[None]]

# 加载主脚本（带连字符不能 import，用 spec）
spec = importlib.util.spec_from_file_location("w", ROOT / "scripts" / "weekend_full_2026-05-24.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

from backtest import STOCK_NAMES

OUT_DIR = ROOT / "output" / "weekly_full_2026-05-24"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 把 STOCK_NAMES 全部补齐
STOCK_NAMES.update(m.EXPANDED_UNIVERSE)

# 收集所有有 CSV 的股票
codes = sorted([
    c for c in m.EXPANDED_UNIVERSE
    if (Path(m.DATA_DIR) / f"{c}.csv").exists()
])
print(f"全 walk-forward：{len(codes)} 股 × {len(m.STRATEGIES)} 策略 = {len(codes)*len(m.STRATEGIES)} 次", flush=True)
print("=" * 100, flush=True)

t0 = time.time()
rows = []
for code in codes:
    name = STOCK_NAMES.get(code, code)
    try:
        in_p, out_p = m.split_csv_in_out(code, ratio=0.7)
    except Exception as e:
        print(f"  ❌ {code} 切分失败：{e}", flush=True)
        continue
    cash = m._cash_for(code)
    for strat in m.STRATEGIES:
        try:
            r_in = m.run_backtest_with_path(in_p, strat, cash=cash)
            r_out = m.run_backtest_with_path(out_p, strat, cash=cash)
            row = {
                "code": code, "name": name, "strategy": strat,
                "in_total": r_in["total_return"], "in_annual": r_in["annual_return"],
                "in_sharpe": r_in["sharpe"], "in_trades": r_in["trades"],
                "out_total": r_out["total_return"], "out_annual": r_out["annual_return"],
                "out_sharpe": r_out["sharpe"], "out_trades": r_out["trades"],
            }
            row["degradation"] = r_in["annual_return"] - r_out["annual_return"]
            rows.append(row)
            print(
                f"  {code} {name[:6]:<6} {strat:<14} "
                f"IN {r_in['annual_return']:>+7.2f}% | OUT {r_out['annual_return']:>+7.2f}% | "
                f"衰减 {row['degradation']:>+6.2f}pp",
                flush=True,
            )
        except Exception as e:
            print(f"  ❌ {code} {strat}: {e}", flush=True)

print(f"\n完成，{len(rows)} 行结果，用时 {time.time()-t0:.1f}s", flush=True)

# ──── 写报告 ────
out_md = OUT_DIR / "C_FULL_walkforward_31stocks.md"

with out_md.open("w", encoding="utf-8") as f:
    f.write(f"# C-FULL: 全 {len(codes)} 股 × {len(m.STRATEGIES)} 策略 Walk-forward 检验\n\n")
    f.write(f"- 切分：前 70% IN-sample / 后 30% OUT-sample\n")
    f.write(f"- 共 {len(rows)} 行结果\n\n")

    # 各策略的 OUT 期统计
    f.write("## 各策略 OUT 样本外统计\n\n")
    f.write("| 策略 | 平均 OUT 年化 | 中位数 OUT 年化 | OUT 正收益占比 | 平均衰减 (pp) | 衰减 ≤ 5pp 占比 |\n")
    f.write("|---|---:|---:|---:|---:|---:|\n")
    by_s = defaultdict(list)
    for r in rows:
        by_s[r["strategy"]].append(r)
    for s, lst in by_s.items():
        n = len(lst)
        out_arr = sorted([r["out_annual"] for r in lst])
        deg_arr = [r["degradation"] for r in lst]
        avg_out = sum(out_arr) / n
        med_out = out_arr[n // 2]
        pos = sum(1 for x in out_arr if x > 0) / n * 100
        avg_deg = sum(deg_arr) / n
        ok_deg = sum(1 for x in deg_arr if x <= 5) / n * 100
        f.write(
            f"| {s} | {avg_out:+.2f}% | {med_out:+.2f}% | {pos:.0f}% | {avg_deg:+.2f} | {ok_deg:.0f}% |\n"
        )

    # 通过 walk-forward 的鲁棒组合 (衰减 ≤ 5pp & OUT 年化 > 0 & OUT 交易 ≥ 1)
    robust = [r for r in rows if r["degradation"] <= 5
              and r["out_annual"] > 0 and r["out_trades"] >= 1
              and not (r["in_total"] < 1 and r["out_total"] < 5)]  # 排除原地不动
    robust.sort(key=lambda x: -x["out_annual"])

    f.write(f"\n## 🌟 通过 walk-forward 的鲁棒组合 ({len(robust)} 个)\n\n")
    f.write("筛选：衰减 ≤ 5pp + OUT 年化 > 0 + OUT 交易 ≥ 1 + 排除原地不动 (IN 总收益 < 1% 且 OUT 总收益 < 5%)\n\n")
    f.write("| 排名 | 股票 | 策略 | OUT 年化 | OUT 夏普 | OUT 交易 | 衰减 (pp) | IN 年化 |\n")
    f.write("|---|---|---|---:|---:|---:|---:|---:|\n")
    for i, r in enumerate(robust, 1):
        f.write(
            f"| {i} | {r['code']} {r['name']} | {r['strategy']} | "
            f"{r['out_annual']:+.2f}% | {r['out_sharpe']:+.2f} | {r['out_trades']} | "
            f"{r['degradation']:+.2f} | {r['in_annual']:+.2f}% |\n"
        )

    # 按衰减排序的全量
    f.write(f"\n## 全量结果（按衰减升序）\n\n")
    f.write("| 股票 | 策略 | IN 年化 | OUT 年化 | 衰减 (pp) | OUT 夏普 | OUT 交易 |\n")
    f.write("|---|---|---:|---:|---:|---:|---:|\n")
    for r in sorted(rows, key=lambda x: x["degradation"]):
        tag = ""
        if r["degradation"] <= 5: tag = " ✅"
        elif r["degradation"] >= 30: tag = " ⚠️"
        f.write(
            f"| {r['code']} {r['name']} | {r['strategy']} | "
            f"{r['in_annual']:+.2f}% | {r['out_annual']:+.2f}% | "
            f"{r['degradation']:+.2f}{tag} | {r['out_sharpe']:+.2f} | {r['out_trades']} |\n"
        )

    # 最危险的（过拟合 top）
    f.write(f"\n## ⚠️ 最易过拟合 Top 10 (衰减最大)\n\n")
    f.write("| 股票 | 策略 | IN 年化 | OUT 年化 | 衰减 (pp) |\n|---|---|---:|---:|---:|\n")
    for r in sorted(rows, key=lambda x: -x["degradation"])[:10]:
        f.write(f"| {r['code']} {r['name']} | {r['strategy']} | {r['in_annual']:+.2f}% | {r['out_annual']:+.2f}% | {r['degradation']:+.2f} |\n")

print(f"\n✅ 报告：{out_md}", flush=True)
