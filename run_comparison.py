#!/usr/bin/env python3
"""
生成多策略对比报告和对比收益曲线图
"""

import os
import sys
import csv
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import warnings
warnings.filterwarnings("ignore")

# Add project root to path
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from backtest import run_backtest, STOCK_NAMES, OUTPUT_DIR


def generate_comparison_chart(results_by_stock):
    """Generate comparison charts for each stock"""
    for stock_code, results in results_by_stock.items():
        stock_name = STOCK_NAMES.get(stock_code, stock_code)

        fig, axes = plt.subplots(2, 1, figsize=(18, 14))

        # --- Top: Cumulative return curves ---
        ax1 = axes[0]
        colors = ["#e74c3c", "#3498db", "#2ecc71", "#9b59b6", "#f39c12"]
        linestyles = ["-", "--", "-."]

        for i, result in enumerate(results):
            time_returns = result.get("time_returns", {})
            if not time_returns:
                continue
            dates = sorted(time_returns.keys())
            cumulative = []
            cum_ret = 1.0
            for d in dates:
                cum_ret *= (1 + time_returns[d])
                cumulative.append((cum_ret - 1) * 100)
            color = colors[i % len(colors)]
            ls = linestyles[i % len(linestyles)] if i > 0 else "-"
            ax1.plot(dates, cumulative, linewidth=2.5,
                     label=f"{result['strategy']} ({result['total_return']:+.1f}%)",
                     color=color, linestyle=ls)

        ax1.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
        ax1.set_title(f"{stock_name}({stock_code}) - 多策略收益对比曲线",
                      fontsize=16, fontweight="bold")
        ax1.set_ylabel("累计收益率 (%)", fontsize=12)
        ax1.legend(fontsize=12, loc="upper left")
        ax1.grid(True, alpha=0.3)

        # --- Bottom: Bar chart comparison ---
        ax2 = axes[1]
        strategies = [r["strategy"] for r in results]
        x = range(len(strategies))
        width = 0.18

        total_returns = [r["total_return"] for r in results]
        annual_returns = [r["annual_return"] for r in results]
        max_drawdowns = [r["max_drawdown"] for r in results]
        win_rates = [r["win_rate"] for r in results]
        sharpes = [r["sharpe_ratio"] for r in results]

        bars1 = ax2.bar([i - 1.5*width for i in x], total_returns, width,
                        label="总收益率%", color="#e74c3c", alpha=0.85)
        bars2 = ax2.bar([i - 0.5*width for i in x], annual_returns, width,
                        label="年化收益率%", color="#3498db", alpha=0.85)
        bars3 = ax2.bar([i + 0.5*width for i in x], [-d for d in max_drawdowns], width,
                        label="最大回撤%(负)", color="#2ecc71", alpha=0.85)
        bars4 = ax2.bar([i + 1.5*width for i in x], win_rates, width,
                        label="胜率%", color="#9b59b6", alpha=0.85)

        ax2.set_xticks(list(x))
        ax2.set_xticklabels(strategies, fontsize=12)
        ax2.set_ylabel("百分比 (%)", fontsize=12)
        ax2.set_title("关键指标对比", fontsize=14, fontweight="bold")
        ax2.legend(fontsize=11)
        ax2.grid(True, alpha=0.3, axis='y')
        ax2.axhline(y=0, color="gray", linewidth=0.8)

        for bars in [bars1, bars2, bars3, bars4]:
            for bar in bars:
                height = bar.get_height()
                if abs(height) > 0.5:
                    ax2.text(bar.get_x() + bar.get_width()/2., height,
                            f'{height:.1f}', ha='center',
                            va='bottom' if height >= 0 else 'top',
                            fontsize=9, fontweight="bold")

        plt.tight_layout()
        fig_path = os.path.join(OUTPUT_DIR, f"{stock_code}_comparison.png")
        fig.savefig(fig_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        print(f"📈 对比图已保存: {fig_path}")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    stocks = ["000967", "002256"]
    strategies = ["macd_strategy", "composite", "composite_v2"]
    strategy_display_order = {
        "macd_strategy": "MACD策略",
        "composite": "复合策略",
        "composite_v2": "自适应复合策略V2",
    }

    results_by_stock = defaultdict(list)
    all_results = []

    for stock in stocks:
        for strat in strategies:
            try:
                result = run_backtest(stock, strat, 100000.0, verbose=False)
                results_by_stock[stock].append(result)
                all_results.append(result)
            except Exception as e:
                print(f"⚠ {stock} - {strat} 失败: {e}")

    # Generate comparison charts
    generate_comparison_chart(results_by_stock)

    # Print comparison table
    print(f"\n{'='*110}")
    print(f"{'📊 多策略回测对比报告':^110}")
    print(f"{'='*110}")

    header = (f"{'股票':<12} {'策略':<20} {'总收益率':>10} {'年化收益':>10} "
              f"{'最大回撤':>10} {'夏普比率':>10} {'交易次数':>8} {'胜率':>8}")
    print(header)
    print("-" * 110)

    for r in all_results:
        line = (f"{r['stock_name']:<12} {r['strategy']:<20} "
                f"{r['total_return']:>+9.2f}% {r['annual_return']:>+9.2f}% "
                f"{r['max_drawdown']:>9.2f}% {r['sharpe_ratio']:>10.4f} "
                f"{r['total_trades']:>8} {r['win_rate']:>7.1f}%")
        print(line)

    print("=" * 110)

    # Save summary CSV
    csv_path = os.path.join(OUTPUT_DIR, "summary.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["stock_code", "stock_name", "strategy", "total_return",
                         "annual_return", "max_drawdown", "sharpe_ratio", "trades", "win_rate"])
        for r in all_results:
            writer.writerow([
                r["stock_code"], r["stock_name"], r["strategy"],
                f"{r['total_return']:+.2f}%", f"{r['annual_return']:+.2f}%",
                f"{r['max_drawdown']:.2f}%", f"{r['sharpe_ratio']:.4f}",
                r["total_trades"], f"{r['win_rate']:.1f}%"
            ])
    print(f"\n📄 汇总CSV: {csv_path}")


if __name__ == "__main__":
    main()
