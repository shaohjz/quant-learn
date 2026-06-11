"""离线回测：5 策略 × 4 股票，2026-05-23 周末快跑

跑完输出 markdown 周报。无网络依赖（用 data/*.csv）。
跑前 monkey-patch 三件事：
  1. 屏蔽 backtest.py 中不带 verbose 阔的 print（重定向 stdout）
  2. 屏蔽 cerebro.plot（无 GUI 卡死）
  3. matplotlib Agg backend
"""
from __future__ import annotations
import sys
import time
import io
import contextlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import warnings
warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")

import backtrader as bt  # noqa: E402
# 禁用 cerebro.plot（33 行那里会卡死）
bt.Cerebro.plot = lambda self, *a, **kw: [[None]]

from backtest import run_backtest, STOCK_NAMES  # noqa: E402

STOCKS = ["000967", "002256", "002453", "600330"]
STRATEGIES = ["sma_cross", "macd_strategy", "bollinger_strategy", "composite", "composite_v2"]
INIT_CASH = 100_000.0

print(f"开始：{len(STOCKS)} 股票 × {len(STRATEGIES)} 策略 = {len(STOCKS)*len(STRATEGIES)} 次回测", flush=True)
print("=" * 100, flush=True)

t0 = time.time()
rows = []
for code in STOCKS:
    name = STOCK_NAMES.get(code, code)
    for strat in STRATEGIES:
        ts = time.time()
        try:
            # 重定向 backtest.py 中调 print
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                r = run_backtest(code, strat, INIT_CASH, verbose=False)
            dur = time.time() - ts
            rows.append(r)
            print(
                f"  [{dur:>5.1f}s] {code} {name:<10} {strat:<14} "
                f"收益 {r['total_return']:>+8.2f}%  年化 {r['annual_return']:>+7.2f}%  "
                f"回撤 {r['max_drawdown']:>5.2f}%  夏普 {r['sharpe_ratio']:>+5.2f}  "
                f"交易 {r['total_trades']:>3}  胜率 {r['win_rate']:>5.1f}%",
                flush=True,
            )
        except Exception as e:
            dur = time.time() - ts
            print(f"  [{dur:>5.1f}s] {code} {name} {strat}  ❌ {type(e).__name__}: {e}", flush=True)

print("=" * 100, flush=True)
print(f"全部完成，用时 {time.time()-t0:.1f}s\n", flush=True)

# 输出周报 markdown
out = ROOT / "output" / "weekly_backtest_20260523.md"
out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w", encoding="utf-8") as f:
    f.write("# 周末离线回测周报 2026-05-23\n\n")
    f.write(f"- 数据：本地 CSV（{', '.join(STOCKS)}）\n")
    f.write(f"- 策略：{', '.join(STRATEGIES)}\n")
    f.write(f"- 初始资金：¥{INIT_CASH:,.0f}\n\n")
    f.write("## 全量结果\n\n")
    f.write("| 股票 | 策略 | 总收益 | 年化 | 最大回撤 | 夏普 | 交易 | 胜率 |\n")
    f.write("|---|---|---:|---:|---:|---:|---:|---:|\n")
    for r in rows:
        f.write(
            f"| {r['stock_code']} {r['stock_name']} | {r['strategy']} | "
            f"{r['total_return']:+.2f}% | {r['annual_return']:+.2f}% | "
            f"{r['max_drawdown']:.2f}% | {r['sharpe_ratio']:.2f} | "
            f"{r['total_trades']} | {r['win_rate']:.1f}% |\n"
        )
    rows_sorted = sorted(rows, key=lambda x: -x["total_return"])
    f.write("\n## 🏆 总收益 Top 5\n\n")
    f.write("| 排名 | 股票×策略 | 总收益 | 年化 | 夏普 |\n|---|---|---:|---:|---:|\n")
    for i, r in enumerate(rows_sorted[:5], 1):
        f.write(
            f"| {i} | {r['stock_code']} {r['stock_name']} × {r['strategy']} | "
            f"{r['total_return']:+.2f}% | {r['annual_return']:+.2f}% | {r['sharpe_ratio']:.2f} |\n"
        )

print(f"✅ 周报已保存：{out}")
