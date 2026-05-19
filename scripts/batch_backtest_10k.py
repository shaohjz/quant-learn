"""
极简批量回测 - 自己组装 cerebro，不调 backtest.py 里的 run_backtest（避免 plot hang）
1 万本金 vs 所有股票 vs 所有策略
"""
import sys, os, csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")

import backtrader as bt
import backtrader.analyzers as btanalyzers
from backtest import StampDutyCommission, STRATEGY_MAP

STOCKS = [("000967", "盈峰环境"), ("002256", "兆新股份"),
          ("002453", "华软科技"), ("600330", "天通股份")]
STRATEGIES = ["sma_cross", "macd_strategy", "bollinger_strategy", "composite", "composite_v2"]
INITIAL_CASH = 10000.0

results = []

def load_strategy(strategy_name):
    module_path, class_name, display_name = STRATEGY_MAP[strategy_name]
    module = __import__(module_path, fromlist=[class_name])
    return getattr(module, class_name), display_name


for code, name in STOCKS:
    csv_path = ROOT / "data" / f"{code}.csv"
    if not csv_path.exists():
        print(f"⚠️ {name}({code}) 无数据，跳过", flush=True)
        continue
    
    for strat_key in STRATEGIES:
        try:
            strat_class, strat_name = load_strategy(strat_key)
            
            cerebro = bt.Cerebro()
            data = bt.feeds.GenericCSVData(
                dataname=str(csv_path),
                dtformat="%Y-%m-%d",
                datetime=0, open=1, high=2, low=3, close=4, volume=5,
                openinterest=-1, headers=True,
            )
            cerebro.adddata(data)
            
            kwargs = {}
            if strat_key in ("composite", "composite_v2"):
                kwargs["printlog"] = False
            cerebro.addstrategy(strat_class, **kwargs)
            
            cerebro.broker.setcash(INITIAL_CASH)
            cerebro.broker.addcommissioninfo(StampDutyCommission())
            
            cerebro.addanalyzer(btanalyzers.SharpeRatio, _name="sharpe", riskfreerate=0.03, annualize=True)
            cerebro.addanalyzer(btanalyzers.DrawDown, _name="drawdown")
            cerebro.addanalyzer(btanalyzers.TradeAnalyzer, _name="trades")
            cerebro.addanalyzer(btanalyzers.Returns, _name="returns")
            
            if strat_key not in ("composite", "composite_v2"):
                cerebro.addsizer(bt.sizers.FixedSize, stake=100)
            
            start = cerebro.broker.getvalue()
            res = cerebro.run()
            end = cerebro.broker.getvalue()
            s = res[0]
            
            tr = (end - start) / start * 100
            
            ar_obj = s.analyzers.returns.get_analysis()
            annual = ar_obj.get("rnorm100", 0) or 0
            
            dd = s.analyzers.drawdown.get_analysis()
            max_dd = dd.max.drawdown if dd.max.drawdown else 0
            
            sh = s.analyzers.sharpe.get_analysis().get("sharperatio") or 0
            
            ta = s.analyzers.trades.get_analysis()
            n_total = ta.get("total", {}).get("total", 0)
            n_won = ta.get("won", {}).get("total", 0)
            n_lost = ta.get("lost", {}).get("total", 0)
            n_closed = n_won + n_lost
            wr = (n_won / n_closed * 100) if n_closed > 0 else 0
            
            r = {
                "code": code, "name": name, "strat": strat_name, "strat_key": strat_key,
                "final": end, "pnl": end - start, "total_return": tr,
                "annual": annual, "max_dd": max_dd, "sharpe": sh,
                "trades": n_total, "win_rate": wr,
            }
            results.append(r)
            print(f"  ✓ {name:<6}({code}) {strat_name:<18} 终值¥{end:>9,.2f} 收益{tr:>+7.2f}% 年化{annual:>+6.2f}% 回撤{max_dd:>5.2f}% 夏普{sh:>+6.2f} 交易{n_total:>3} 胜率{wr:>4.1f}%", flush=True)
        except Exception as e:
            print(f"  ✗ {name}({code}) {strat_key}: {type(e).__name__}: {e}", flush=True)

# 排名
print("\n" + "=" * 110)
print(f"  📊 排名 (按总收益)  | 初始资金 ¥{INITIAL_CASH:,.0f}")
print("=" * 110)
print(f"  {'#':<4}{'股票':<8}{'策略':<20}{'最终市值':>12}{'盈亏':>10}{'总收益':>10}{'年化':>10}{'回撤':>8}{'夏普':>8}{'交易':>5}{'胜率':>7}")
print("-" * 110)
for i, r in enumerate(sorted(results, key=lambda x: -x["total_return"]), 1):
    print(f"  {i:<4}{r['name']:<8}{r['strat']:<20}¥{r['final']:>10,.2f}{r['pnl']:>+9.0f}{r['total_return']:>+9.2f}%{r['annual']:>+9.2f}%{r['max_dd']:>7.2f}%{r['sharpe']:>+7.2f}{r['trades']:>6}{r['win_rate']:>6.1f}%")
print("=" * 110)

# 写 csv
out = ROOT / "output" / "summary_10k.csv"
with open(out, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["代码", "名称", "策略", "终值", "盈亏", "总收益%", "年化%", "回撤%", "夏普", "交易", "胜率%"])
    for r in sorted(results, key=lambda x: -x["total_return"]):
        w.writerow([r["code"], r["name"], r["strat"],
                    f"{r['final']:.2f}", f"{r['pnl']:+.2f}",
                    f"{r['total_return']:+.2f}", f"{r['annual']:+.2f}",
                    f"{r['max_dd']:.2f}", f"{r['sharpe']:+.4f}",
                    r["trades"], f"{r['win_rate']:.1f}"])
print(f"💾 已保存: {out}\n✅ 完成")
