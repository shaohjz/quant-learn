"""
vqlearn/runners/run_backtest_v2.py

多策略 × 多股票批量回测 → 输出 leaderboard。

用法：
  python -m vqlearn.runners.run_backtest_v2 --start 2024-01-01 --end 2026-05-21
  python -m vqlearn.runners.run_backtest_v2 --strategies threshold_alert,macd --top 5
"""
from __future__ import annotations
import sys
import argparse
import yaml
from pathlib import Path
from datetime import datetime
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vqlearn.services.backtest_engine import run_backtest
from vqlearn.services.history_loader import load_history
from vqlearn.strategies.pure_signals import ALL_STRATEGIES, get_strategy

CONFIG_PATH = ROOT / 'vqlearn' / 'config' / 'portfolio.yaml'
OUTPUT_DIR = ROOT / 'output' / 'backtest_v2'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--start', default='2024-01-01', help='回测起始日（YYYY-MM-DD）')
    p.add_argument('--end', default=None, help='回测截止日，默认今天')
    p.add_argument('--strategies', default='all', help='逗号分隔的策略 ID，all=全部')
    p.add_argument('--initial', type=float, default=10000.0, help='单股本金')
    p.add_argument('--top', type=int, default=10, help='leaderboard 显示前 N')
    p.add_argument('--codes', default=None, help='逗号分隔的股票代码，None=用 portfolio.yaml')
    args = p.parse_args()

    # 选股票
    if args.codes:
        items = [{'symbol': c, 'name': c, 'rules': {}} for c in args.codes.split(',')]
    else:
        cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding='utf-8'))
        holdings = cfg.get('holdings', []) or []
        watchlist = cfg.get('watchlist', []) or []
        items = holdings + watchlist

    # 选策略
    if args.strategies == 'all':
        strategy_ids = list(ALL_STRATEGIES.keys())
    else:
        strategy_ids = [s.strip() for s in args.strategies.split(',')]

    end = args.end or datetime.now().strftime('%Y-%m-%d')

    print(f"\n{'='*100}")
    print(f"📊 vqlearn 回测 V2 | {args.start} ~ {end} | {len(items)} 股 × {len(strategy_ids)} 策略 = {len(items)*len(strategy_ids)} 个回测")
    print(f"{'='*100}\n")

    all_results = []

    for item in items:
        code = item['symbol']
        name = item.get('name', code)
        rules = item.get('rules') or {}

        print(f"  📈 {code} {name} ...", end='', flush=True)
        bars = load_history(code, args.start, end)
        if bars.empty or len(bars) < 30:
            print(f" ⚠️ 数据不足 ({len(bars)} bars)")
            continue
        print(f" {len(bars)} bars", end='', flush=True)

        for sid in strategy_ids:
            try:
                strategy = get_strategy(sid)
                result = run_backtest(bars, strategy, rules, code, name, initial_cash=args.initial)
                all_results.append(result.to_dict())
            except Exception as e:
                print(f" [{sid} 失败: {e}]", end='')
        print()  # 换行

    if not all_results:
        print("⚠️ 没有任何回测结果")
        return

    # ==== 保存原始结果 ====
    df = pd.DataFrame(all_results)
    raw_csv = OUTPUT_DIR / f'raw_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    df.to_csv(raw_csv, index=False)
    print(f"\n✅ 原始结果: {raw_csv}")

    # ==== Leaderboard：按策略分组求平均 ====
    print(f"\n{'='*100}")
    print(f"🏆 Strategy Leaderboard（按策略 × 股票计算综合指标）")
    print(f"{'='*100}\n")

    summary = df.groupby('strategy_id').agg(
        avg_return=('total_return_pct', 'mean'),
        avg_annual=('annual_return_pct', 'mean'),
        avg_drawdown=('max_drawdown_pct', 'mean'),
        avg_sharpe=('sharpe_ratio', 'mean'),
        avg_winrate=('win_rate_pct', 'mean'),
        avg_pf=('profit_factor', 'mean'),
        avg_trades=('trades_count', 'mean'),
        n_stocks=('code', 'count'),
    ).round(2)

    # 综合分（参考 STRATEGY_AGENTS.md 的公式）
    summary['score'] = (
        summary['avg_annual'] * 0.25
        + summary['avg_sharpe'] * 15
        + (100 - summary['avg_drawdown']) * 0.20
        + summary['avg_winrate'] * 0.15
        + summary['avg_pf'].clip(upper=5) * 5
    ).round(2)

    summary = summary.sort_values('score', ascending=False)
    print(summary.to_string())
    summary.to_csv(OUTPUT_DIR / 'leaderboard.csv')

    # ==== 单股票冠军（哪只股票哪个策略最好）====
    print(f"\n{'='*100}")
    print(f"🥇 各股票最佳策略（Top {args.top}）")
    print(f"{'='*100}\n")

    by_stock = df.sort_values('total_return_pct', ascending=False).head(args.top)
    print(by_stock[['code', 'name', 'strategy_id', 'total_return_pct', 'annual_return_pct',
                    'max_drawdown_pct', 'sharpe_ratio', 'win_rate_pct', 'trades_count']].to_string(index=False))

    # 保存为 baseline（首次跑作为 master 基线）
    baseline_path = ROOT / 'output' / 'baseline_backtest.csv'
    if not baseline_path.exists():
        df.to_csv(baseline_path, index=False)
        print(f"\n📌 首次回测，已保存为 master 基线: {baseline_path}")
    else:
        # 对比基线
        compare_path = OUTPUT_DIR / f'compare_vs_baseline_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        baseline = pd.read_csv(baseline_path)
        merged = df.merge(baseline, on=['strategy_id', 'code'], suffixes=('_new', '_base'), how='outer')
        merged['return_diff'] = merged['total_return_pct_new'] - merged['total_return_pct_base']
        merged.to_csv(compare_path, index=False)
        print(f"\n📊 对比基线: {compare_path}")


if __name__ == '__main__':
    main()
