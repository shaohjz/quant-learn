#!/usr/bin/env python3
"""
A股量化回测主程序

用法:
    python3 backtest.py --stock 000967 --strategy sma_cross
    python3 backtest.py --stock 002256 --strategy macd_strategy
    python3 backtest.py --stock 000967 --strategy composite
    python3 backtest.py --stock 000967 --strategy composite_v2
    python3 backtest.py --stock 000967 --strategy all   # 运行所有策略并对比
"""

import os
import sys
import argparse
import math
import csv
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import warnings
warnings.filterwarnings("ignore", category=UserWarning, message=".*Glyph.*")
import backtrader as bt
import backtrader.analyzers as btanalyzers
from datetime import datetime

# 项目根目录
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")

# 策略映射
STRATEGY_MAP = {
    "sma_cross": ("strategies.sma_cross", "SmaCross", "双均线策略"),
    "macd_strategy": ("strategies.macd_strategy", "MacdStrategy", "MACD策略"),
    "bollinger_strategy": ("strategies.bollinger_strategy", "BollingerStrategy", "布林带策略"),
    "composite": ("strategies.composite_strategy", "CompositeStrategy", "复合策略"),
    "composite_v2": ("strategies.composite_v2", "CompositeV2Strategy", "自适应复合策略V2"),
}

# 股票名称映射
STOCK_NAMES = {
    "000967": "盈峰环境",
    "002256": "兆新股份",
    "002453": "华软科技",
    "600330": "天通股份",
}


class StampDutyCommission(bt.CommInfoBase):
    """
    A股手续费模型：
    - 双边手续费 0.1%
    - 卖出印花税 0.05%
    """
    params = (
        ("commission", 0.001),
        ("stamp_duty", 0.0005),
        ("stocklike", True),
        ("commtype", bt.CommInfoBase.COMM_PERC),
    )

    def _getcommission(self, size, price, pseudoexec):
        turnover = abs(size) * price
        commission = turnover * self.p.commission
        if size < 0:
            commission += turnover * self.p.stamp_duty
        return max(commission, 5.0)


def load_strategy(strategy_name: str):
    """动态加载策略类"""
    if strategy_name not in STRATEGY_MAP:
        raise ValueError(f"未知策略: {strategy_name}，可选: {list(STRATEGY_MAP.keys())}")

    module_path, class_name, display_name = STRATEGY_MAP[strategy_name]
    module = __import__(module_path, fromlist=[class_name])
    strategy_class = getattr(module, class_name)
    return strategy_class, display_name


def compute_monthly_returns(time_returns):
    """从每日收益计算月度收益"""
    if not time_returns:
        return {}

    monthly = defaultdict(lambda: 1.0)
    for dt, ret in sorted(time_returns.items()):
        key = dt.strftime("%Y-%m") if hasattr(dt, 'strftime') else str(dt)[:7]
        monthly[key] *= (1 + ret)

    return {k: (v - 1) * 100 for k, v in sorted(monthly.items())}


def run_backtest(stock_code: str, strategy_name: str, initial_cash: float = 100000.0,
                 verbose: bool = True):
    """
    执行回测

    Returns:
        dict: 回测结果
    """
    csv_path = os.path.join(DATA_DIR, f"{stock_code}.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"数据文件不存在: {csv_path}，请先运行 data/fetch_data.py")

    strategy_class, strategy_display = load_strategy(strategy_name)
    stock_name = STOCK_NAMES.get(stock_code, stock_code)

    print(f"\n{'='*60}")
    print(f"回测: {stock_name}({stock_code}) - {strategy_display}")
    print(f"{'='*60}")

    # 创建引擎
    cerebro = bt.Cerebro()

    # 加载数据
    data = bt.feeds.GenericCSVData(
        dataname=csv_path,
        dtformat="%Y-%m-%d",
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        headers=True,
    )
    cerebro.adddata(data, name=f"{stock_name}({stock_code})")

    # 添加策略 (enable logging for composite strategies)
    strategy_kwargs = {}
    if strategy_name in ("composite", "composite_v2"):
        strategy_kwargs["printlog"] = verbose
    cerebro.addstrategy(strategy_class, **strategy_kwargs)

    # 资金与手续费
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.addcommissioninfo(StampDutyCommission())

    # 每次交易由策略自身控制仓位，不使用 sizer
    # (composite strategies manage position sizing internally)

    # 添加分析器
    cerebro.addanalyzer(btanalyzers.SharpeRatio, _name="sharpe", riskfreerate=0.03, annualize=True)
    cerebro.addanalyzer(btanalyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(btanalyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(btanalyzers.Returns, _name="returns")
    cerebro.addanalyzer(btanalyzers.TimeReturn, _name="time_return")

    # For old strategies that don't have their own sizing, add a sizer
    if strategy_name not in ("composite", "composite_v2"):
        cerebro.addsizer(bt.sizers.FixedSize, stake=100)

    # 运行
    start_value = cerebro.broker.getvalue()
    results = cerebro.run()
    end_value = cerebro.broker.getvalue()
    strat = results[0]

    # 提取分析结果
    total_return = (end_value - start_value) / start_value * 100

    time_returns = strat.analyzers.time_return.get_analysis()
    n_days = len(time_returns) if time_returns else 1
    n_years = n_days / 252.0
    annual_return = ((end_value / start_value) ** (1 / max(n_years, 0.01)) - 1) * 100 if n_years > 0 else 0

    dd = strat.analyzers.drawdown.get_analysis()
    max_drawdown = dd.max.drawdown if dd.max.drawdown else 0

    sharpe = strat.analyzers.sharpe.get_analysis()
    sharpe_ratio = sharpe.get("sharperatio", None)
    if sharpe_ratio is None:
        sharpe_ratio = 0.0

    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    won_trades = trade_analysis.get("won", {}).get("total", 0)
    lost_trades = trade_analysis.get("lost", {}).get("total", 0)
    closed_trades = won_trades + lost_trades
    win_rate = (won_trades / closed_trades * 100) if closed_trades > 0 else 0

    # Monthly returns
    monthly_returns = compute_monthly_returns(time_returns)

    result = {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "strategy": strategy_display,
        "strategy_key": strategy_name,
        "initial_cash": initial_cash,
        "final_value": end_value,
        "total_return": total_return,
        "annual_return": annual_return,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "total_trades": total_trades,
        "won_trades": won_trades,
        "lost_trades": lost_trades,
        "win_rate": win_rate,
        "monthly_returns": monthly_returns,
        "time_returns": time_returns,
    }

    # 打印结果
    print(f"\n📊 回测结果:")
    print(f"  初始资金:     ¥{initial_cash:,.2f}")
    print(f"  最终市值:     ¥{end_value:,.2f}")
    print(f"  总收益率:     {total_return:+.2f}%")
    print(f"  年化收益率:   {annual_return:+.2f}%")
    print(f"  最大回撤:     {max_drawdown:.2f}%")
    print(f"  夏普比率:     {sharpe_ratio:.4f}")
    print(f"  交易次数:     {total_trades}")
    print(f"  胜率:         {win_rate:.1f}% ({won_trades}胜/{lost_trades}负)")

    # 月度收益
    if monthly_returns:
        print(f"\n📅 月度收益:")
        for month, ret in monthly_returns.items():
            bar = "🟢" if ret >= 0 else "🔴"
            print(f"  {month}: {bar} {ret:+.2f}%")

    # 生成收益曲线图
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    fig_path = os.path.join(OUTPUT_DIR, f"{stock_code}_{strategy_name}.png")

    try:
        fig = cerebro.plot(style="candlestick", barup="red", bardown="green",
                          volume=True, figsize=(16, 10))[0][0]
        fig.savefig(fig_path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        print(f"  收益曲线图:   {fig_path}")
    except Exception as e:
        print(f"  ⚠ 图表生成失败: {e}")
        try:
            generate_simple_chart(time_returns, stock_name, stock_code,
                                strategy_display, result, fig_path)
            print(f"  收益曲线图(简化版): {fig_path}")
        except Exception as e2:
            print(f"  ⚠ 简化图表也失败了: {e2}")

    result["chart_path"] = fig_path
    return result


def generate_simple_chart(time_returns, stock_name, stock_code,
                         strategy_display, result, fig_path):
    """生成简化的收益曲线图"""
    if not time_returns:
        return

    dates = sorted(time_returns.keys())
    cumulative = []
    cum_ret = 1.0
    for d in dates:
        cum_ret *= (1 + time_returns[d])
        cumulative.append((cum_ret - 1) * 100)

    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(dates, cumulative, "b-", linewidth=1.5, label="累计收益率")
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
    ax.fill_between(dates, cumulative, 0,
                    where=[c >= 0 for c in cumulative], alpha=0.1, color="red")
    ax.fill_between(dates, cumulative, 0,
                    where=[c < 0 for c in cumulative], alpha=0.1, color="green")

    ax.set_title(f"{stock_name}({stock_code}) - {strategy_display} 收益曲线",
                fontsize=14, fontweight="bold")
    ax.set_xlabel("日期")
    ax.set_ylabel("累计收益率 (%)")
    ax.legend()
    ax.grid(True, alpha=0.3)

    info_text = (
        f"总收益: {result['total_return']:+.2f}%\n"
        f"年化: {result['annual_return']:+.2f}%\n"
        f"最大回撤: {result['max_drawdown']:.2f}%\n"
        f"夏普: {result['sharpe_ratio']:.4f}\n"
        f"胜率: {result['win_rate']:.1f}%"
    )
    ax.text(0.02, 0.98, info_text, transform=ax.transAxes, fontsize=10,
            verticalalignment="top", bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

    plt.tight_layout()
    fig.savefig(fig_path, dpi=100, bbox_inches="tight")
    plt.close(fig)


def generate_comparison_chart(all_results, stock_code, stock_name):
    """生成多策略对比图"""
    fig, axes = plt.subplots(2, 1, figsize=(16, 12))

    # Top: cumulative return curves
    ax1 = axes[0]
    colors = ["#e74c3c", "#3498db", "#2ecc71", "#9b59b6", "#f39c12"]

    for i, result in enumerate(all_results):
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
        ax1.plot(dates, cumulative, linewidth=2, label=result["strategy"], color=color)

    ax1.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
    ax1.set_title(f"{stock_name}({stock_code}) - 多策略收益对比", fontsize=14, fontweight="bold")
    ax1.set_ylabel("累计收益率 (%)")
    ax1.legend(fontsize=11)
    ax1.grid(True, alpha=0.3)

    # Bottom: bar chart of key metrics
    ax2 = axes[1]
    strategies = [r["strategy"] for r in all_results]
    x = range(len(strategies))
    width = 0.2

    total_returns = [r["total_return"] for r in all_results]
    annual_returns = [r["annual_return"] for r in all_results]
    max_drawdowns = [-r["max_drawdown"] for r in all_results]  # negative for visual
    win_rates = [r["win_rate"] for r in all_results]

    bars1 = ax2.bar([i - 1.5*width for i in x], total_returns, width, label="总收益率%", color="#e74c3c", alpha=0.8)
    bars2 = ax2.bar([i - 0.5*width for i in x], annual_returns, width, label="年化收益率%", color="#3498db", alpha=0.8)
    bars3 = ax2.bar([i + 0.5*width for i in x], max_drawdowns, width, label="最大回撤%(负)", color="#2ecc71", alpha=0.8)
    bars4 = ax2.bar([i + 1.5*width for i in x], win_rates, width, label="胜率%", color="#9b59b6", alpha=0.8)

    ax2.set_xticks(list(x))
    ax2.set_xticklabels(strategies, fontsize=11)
    ax2.set_ylabel("百分比 (%)")
    ax2.set_title("关键指标对比", fontsize=14, fontweight="bold")
    ax2.legend(fontsize=10)
    ax2.grid(True, alpha=0.3, axis='y')
    ax2.axhline(y=0, color="gray", linewidth=0.8)

    # Add value labels on bars
    for bars in [bars1, bars2, bars3, bars4]:
        for bar in bars:
            height = bar.get_height()
            if abs(height) > 0.5:
                ax2.text(bar.get_x() + bar.get_width()/2., height,
                        f'{height:.1f}', ha='center', va='bottom' if height >= 0 else 'top',
                        fontsize=8)

    plt.tight_layout()
    fig_path = os.path.join(OUTPUT_DIR, f"{stock_code}_comparison.png")
    fig.savefig(fig_path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    print(f"\n📈 对比图已保存: {fig_path}")
    return fig_path


def run_comparison(stock_code: str, strategy_names: list, initial_cash: float = 100000.0):
    """Run multiple strategies and compare"""
    stock_name = STOCK_NAMES.get(stock_code, stock_code)
    all_results = []

    for sname in strategy_names:
        try:
            result = run_backtest(stock_code, sname, initial_cash, verbose=True)
            all_results.append(result)
        except Exception as e:
            print(f"⚠ 策略 {sname} 运行失败: {e}")

    if len(all_results) > 1:
        generate_comparison_chart(all_results, stock_code, stock_name)

    return all_results


def print_comparison_table(all_results):
    """Print a formatted comparison table"""
    print(f"\n{'='*100}")
    print(f"{'策略对比汇总':^100}")
    print(f"{'='*100}")

    header = f"{'股票':<12} {'策略':<18} {'总收益率':>10} {'年化收益':>10} {'最大回撤':>10} {'夏普比率':>10} {'交易次数':>8} {'胜率':>8}"
    print(header)
    print("-" * 100)

    for r in all_results:
        line = (f"{r['stock_name']:<12} {r['strategy']:<18} "
                f"{r['total_return']:>+9.2f}% {r['annual_return']:>+9.2f}% "
                f"{r['max_drawdown']:>9.2f}% {r['sharpe_ratio']:>10.4f} "
                f"{r['total_trades']:>8} {r['win_rate']:>7.1f}%")
        print(line)

    print("=" * 100)


def save_summary_csv(all_results):
    """Save summary to CSV"""
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
    print(f"\n📄 汇总CSV已保存: {csv_path}")


def main():
    parser = argparse.ArgumentParser(description="A股量化回测主程序")
    parser.add_argument("--stock", type=str, required=True, help="股票代码")
    parser.add_argument("--strategy", type=str, required=True,
                       choices=list(STRATEGY_MAP.keys()) + ["all"],
                       help="策略名称 (或 'all' 运行所有策略)")
    parser.add_argument("--cash", type=float, default=100000.0, help="初始资金（默认10万）")

    args = parser.parse_args()

    if args.strategy == "all":
        results = run_comparison(args.stock, list(STRATEGY_MAP.keys()), args.cash)
        print_comparison_table(results)
        save_summary_csv(results)
    else:
        result = run_backtest(args.stock, args.strategy, args.cash)

    return 0


if __name__ == "__main__":
    main()
