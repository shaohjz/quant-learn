#!/usr/bin/env python3
"""
scripts/strategy_pk.py — 5 策略 × N 股票 大 PK

不调用 backtrader 的 cerebro.plot（容易卡），只用 analyzer 出指标，
最后用 matplotlib 自己画对比图。

输出：
  output/strategy_pk_summary.csv   汇总表
  output/strategy_pk.png           对比图
  控制台一张漂亮的表格
"""

import os
import sys
import csv
from collections import defaultdict
from datetime import datetime

# 让 import 从项目根目录开始
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings("ignore")

import backtrader as bt
import backtrader.analyzers as btanalyzers

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

STRATEGY_MAP = {
    "sma_cross": ("strategies.sma_cross", "SmaCross", "双均线"),
    "macd_strategy": ("strategies.macd_strategy", "MacdStrategy", "MACD"),
    "bollinger_strategy": ("strategies.bollinger_strategy", "BollingerStrategy", "布林带"),
    "composite": ("strategies.composite_strategy", "CompositeStrategy", "复合"),
    "composite_v2": ("strategies.composite_v2", "CompositeV2Strategy", "复合V2"),
}

STOCK_NAMES = {
    "000967": "盈峰环境",
    "002256": "兆新股份",
}


class StampDutyCommission(bt.CommInfoBase):
    params = (("commission", 0.001), ("stamp_duty", 0.0005),
              ("stocklike", True), ("commtype", bt.CommInfoBase.COMM_PERC))

    def _getcommission(self, size, price, pseudoexec):
        turnover = abs(size) * price
        commission = turnover * self.p.commission
        if size < 0:
            commission += turnover * self.p.stamp_duty
        return max(commission, 5.0)


def load_strategy(name):
    module_path, class_name, display = STRATEGY_MAP[name]
    module = __import__(module_path, fromlist=[class_name])
    return getattr(module, class_name), display


def run_one(stock_code, strategy_name, cash):
    csv_path = os.path.join(DATA_DIR, f"{stock_code}.csv")
    if not os.path.exists(csv_path):
        return None

    cls, display = load_strategy(strategy_name)
    cerebro = bt.Cerebro(stdstats=False)
    data = bt.feeds.GenericCSVData(
        dataname=csv_path, dtformat="%Y-%m-%d",
        datetime=0, open=1, high=2, low=3, close=4, volume=5,
        openinterest=-1, headers=True,
    )
    cerebro.adddata(data)

    kwargs = {"printlog": False} if strategy_name in ("composite", "composite_v2") else {}
    cerebro.addstrategy(cls, **kwargs)
    cerebro.broker.setcash(cash)
    cerebro.broker.addcommissioninfo(StampDutyCommission())
    if strategy_name not in ("composite", "composite_v2"):
        cerebro.addsizer(bt.sizers.FixedSize, stake=100)

    cerebro.addanalyzer(btanalyzers.SharpeRatio, _name="sharpe", riskfreerate=0.03, annualize=True)
    cerebro.addanalyzer(btanalyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(btanalyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(btanalyzers.TimeReturn, _name="time_return")

    start = cerebro.broker.getvalue()
    res = cerebro.run()
    end = cerebro.broker.getvalue()
    s = res[0]

    tr = s.analyzers.time_return.get_analysis()
    n_days = len(tr) if tr else 1
    n_years = n_days / 252.0
    annual = ((end / start) ** (1 / max(n_years, 0.01)) - 1) * 100 if n_years > 0 else 0

    dd = s.analyzers.drawdown.get_analysis()
    sharpe = s.analyzers.sharpe.get_analysis().get("sharperatio") or 0.0
    ta = s.analyzers.trades.get_analysis()
    won = ta.get("won", {}).get("total", 0) or 0
    lost = ta.get("lost", {}).get("total", 0) or 0
    closed = won + lost

    return {
        "stock_code": stock_code,
        "stock_name": STOCK_NAMES.get(stock_code, stock_code),
        "strategy": display,
        "strategy_key": strategy_name,
        "start_value": start,
        "final_value": end,
        "total_return": (end - start) / start * 100,
        "annual_return": annual,
        "max_drawdown": dd.max.drawdown if dd.max.drawdown else 0,
        "sharpe": sharpe,
        "trades": ta.get("total", {}).get("total", 0),
        "win_rate": (won / closed * 100) if closed > 0 else 0,
        "won": won, "lost": lost,
        "time_returns": tr,
    }


def print_table(rows):
    print()
    print("=" * 110)
    print(f"{'股票':<12} {'策略':<10} {'终值':>10} {'总收益%':>10} {'年化%':>9} "
          f"{'最大回撤%':>10} {'夏普':>8} {'交易数':>7} {'胜率%':>7}")
    print("-" * 110)
    rows_sorted = sorted(rows, key=lambda r: -r["total_return"])
    for i, r in enumerate(rows_sorted):
        rank = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "  "
        print(f"{rank}{r['stock_name']:<10} {r['strategy']:<10} "
              f"{r['final_value']:>10.0f} {r['total_return']:>+10.2f} "
              f"{r['annual_return']:>+9.2f} {r['max_drawdown']:>10.2f} "
              f"{r['sharpe']:>8.2f} {r['trades']:>7} {r['win_rate']:>7.1f}")
    print("=" * 110)


def save_csv(rows):
    p = os.path.join(OUTPUT_DIR, "strategy_pk_summary.csv")
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["股票代码", "股票", "策略", "起始资金", "终值",
                    "总收益率%", "年化%", "最大回撤%", "夏普", "交易数", "胜率%"])
        for r in rows:
            w.writerow([r["stock_code"], r["stock_name"], r["strategy"],
                        f"{r['start_value']:.0f}", f"{r['final_value']:.0f}",
                        f"{r['total_return']:+.2f}", f"{r['annual_return']:+.2f}",
                        f"{r['max_drawdown']:.2f}", f"{r['sharpe']:.2f}",
                        r["trades"], f"{r['win_rate']:.1f}"])
    print(f"\n📄 CSV: {p}")
    return p


def plot_pk(rows):
    """画两张：每只股票一张累计收益曲线对比图"""
    by_stock = defaultdict(list)
    for r in rows:
        by_stock[r["stock_code"]].append(r)

    n = len(by_stock)
    fig, axes = plt.subplots(n, 1, figsize=(14, 5 * n), squeeze=False)
    colors = ["#e74c3c", "#3498db", "#2ecc71", "#9b59b6", "#f39c12"]

    for ax_idx, (code, group) in enumerate(by_stock.items()):
        ax = axes[ax_idx][0]
        for i, r in enumerate(group):
            tr = r["time_returns"]
            if not tr:
                continue
            dates = sorted(tr.keys())
            cum = []
            cur = 1.0
            for d in dates:
                cur *= (1 + tr[d])
                cum.append((cur - 1) * 100)
            ax.plot(dates, cum, label=f"{r['strategy']} ({r['total_return']:+.1f}%)",
                    color=colors[i % len(colors)], linewidth=1.8)

        ax.axhline(0, color="gray", linestyle="--", alpha=0.5)
        ax.set_title(f"{group[0]['stock_name']}({code}) 5 strategies PK", fontsize=13)
        ax.set_ylabel("Cumulative Return (%)")
        ax.legend(loc="best", fontsize=10)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    p = os.path.join(OUTPUT_DIR, "strategy_pk.png")
    fig.savefig(p, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"📈 图表: {p}")
    return p


def main():
    cash = 20000
    stocks = list(STOCK_NAMES.keys())
    strategies = list(STRATEGY_MAP.keys())

    print(f"🏁 开始 PK：{len(stocks)} 只股票 × {len(strategies)} 个策略 = {len(stocks)*len(strategies)} 次回测")
    print(f"   初始资金 ¥{cash:,}, 时间区间见 data/*.csv")

    results = []
    for stock in stocks:
        for strat in strategies:
            print(f"  → {stock} × {strat} ...", end=" ", flush=True)
            try:
                r = run_one(stock, strat, cash)
                if r:
                    results.append(r)
                    print(f"OK return={r['total_return']:+.2f}% trades={r['trades']}")
                else:
                    print("跳过")
            except Exception as e:
                print(f"FAIL {e}")

    if not results:
        print("没有有效结果")
        return

    print_table(results)
    save_csv(results)
    plot_pk(results)

    print("\n🏆 总冠军:")
    winner = max(results, key=lambda r: r["total_return"])
    print(f"   {winner['stock_name']}({winner['stock_code']}) - {winner['strategy']}: "
          f"总收益 {winner['total_return']:+.2f}%, 年化 {winner['annual_return']:+.2f}%, "
          f"最大回撤 {winner['max_drawdown']:.2f}%, 夏普 {winner['sharpe']:.2f}")


if __name__ == "__main__":
    main()
