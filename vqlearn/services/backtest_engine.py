"""
vqlearn/services/backtest_engine.py

真回测引擎 v2 - 喂历史 K 线给纯策略层，计算 PnL/胜率/回撤/夏普。

核心特性：
- 调 vqlearn/strategies/pure_signals.py 里的纯策略
- 模拟撮合（每根 K 线取 close 价 + 滑点）
- 手续费：万 2.5 + 印花税 0.05%
- 输出：BacktestResult（含每笔交易、累计 PnL 曲线、各项指标）
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

from vqlearn.strategies.pure_signals import StrategyBase, Signal, get_strategy


# ============== 撮合参数 ==============
COMMISSION_RATE = 0.00025      # 万 2.5
COMMISSION_MIN = 5.0
TAX_RATE = 0.0005              # 印花税 0.05%（仅卖）
SLIPPAGE_PCT = 0.003           # 滑点 0.3%（买价上浮、卖价下浮）
LOT_SIZE = 100                 # A 股最小单位
DEFAULT_BUDGET_LIGHT = 2000.0  # 试探仓预算
DEFAULT_BUDGET_HEAVY = 5000.0  # 加仓预算


@dataclass
class Trade:
    date: str
    direction: str  # 'BUY' | 'SELL'
    qty: int
    price: float
    amount: float
    fee: float
    rule_name: str
    reason: str


@dataclass
class BacktestResult:
    strategy_id: str
    code: str
    name: str
    start_date: str
    end_date: str
    bars_count: int

    initial_cash: float
    final_value: float
    final_cash: float
    final_position: int

    total_return_pct: float
    annual_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate_pct: float
    profit_factor: float

    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)  # [(date, total_value)]
    closed_trades: list = field(default_factory=list)  # 配对的买卖

    def to_dict(self) -> dict:
        return {
            'strategy_id': self.strategy_id,
            'code': self.code,
            'name': self.name,
            'start': self.start_date,
            'end': self.end_date,
            'bars': self.bars_count,
            'final_value': round(self.final_value, 2),
            'total_return_pct': round(self.total_return_pct, 2),
            'annual_return_pct': round(self.annual_return_pct, 2),
            'max_drawdown_pct': round(self.max_drawdown_pct, 2),
            'sharpe_ratio': round(self.sharpe_ratio, 3),
            'win_rate_pct': round(self.win_rate_pct, 2),
            'profit_factor': round(self.profit_factor, 3),
            'trades_count': len(self.trades),
            'closed_trades': len(self.closed_trades),
        }


def _calc_commission(amount: float) -> float:
    return max(amount * COMMISSION_RATE, COMMISSION_MIN)


def run_backtest(
    bars: pd.DataFrame,
    strategy: StrategyBase,
    rules: dict,
    code: str,
    name: str = '',
    initial_cash: float = 10000.0,
    warmup_bars: int = 30,  # 前 N 条不交易（预热指标）
) -> BacktestResult:
    """
    回测主循环。
    bars: 必须有 columns [date, open, high, low, close, volume]，按时间升序
    """
    cash = initial_cash
    position = 0
    avg_cost = 0.0
    trades: list[Trade] = []
    closed_trades: list[dict] = []  # 每对买卖配对
    equity_curve: list = []

    if bars is None or len(bars) <= warmup_bars:
        return BacktestResult(
            strategy_id=strategy.strategy_id, code=code, name=name,
            start_date='', end_date='', bars_count=len(bars) if bars is not None else 0,
            initial_cash=initial_cash, final_value=initial_cash, final_cash=initial_cash, final_position=0,
            total_return_pct=0, annual_return_pct=0, max_drawdown_pct=0,
            sharpe_ratio=0, win_rate_pct=0, profit_factor=0,
        )

    bars = bars.reset_index(drop=True).copy()
    if 'date' not in bars.columns:
        bars['date'] = bars.index.astype(str)

    # 主循环：从 warmup 开始
    for i in range(warmup_bars, len(bars)):
        # 喂截至当前的所有 bars 给策略
        history = bars.iloc[:i+1]
        bar = bars.iloc[i]
        date = str(bar['date'])
        close = float(bar['close'])

        signal = strategy.decide(history, position, rules)

        if signal.action == 'NO_ACTION':
            equity_curve.append((date, cash + position * close))
            continue

        # ===== 执行 =====
        if signal.action.startswith('BUY'):
            if position > 0 and signal.action == 'BUY_LIGHT':
                # 已有仓位时不再 BUY_LIGHT（避免重复加仓）
                equity_curve.append((date, cash + position * close))
                continue

            budget = DEFAULT_BUDGET_HEAVY if signal.action == 'BUY_HEAVY' else DEFAULT_BUDGET_LIGHT
            budget = min(budget, cash * 0.9)
            buy_price = close * (1 + SLIPPAGE_PCT)  # 加滑点
            qty = int(budget / buy_price / LOT_SIZE) * LOT_SIZE
            if qty < LOT_SIZE:
                equity_curve.append((date, cash + position * close))
                continue
            amount = qty * buy_price
            fee = _calc_commission(amount)
            total_cost = amount + fee
            if total_cost > cash:
                equity_curve.append((date, cash + position * close))
                continue

            cash -= total_cost
            new_position = position + qty
            avg_cost = (avg_cost * position + buy_price * qty) / new_position if new_position else buy_price
            position = new_position

            trades.append(Trade(date, 'BUY', qty, buy_price, amount, fee, signal.rule_name, signal.reason))

        elif signal.action.startswith('SELL'):
            if position == 0:
                equity_curve.append((date, cash + position * close))
                continue

            sell_qty = position if signal.action == 'SELL_ALL' else (position // 2 // LOT_SIZE) * LOT_SIZE
            if sell_qty < LOT_SIZE:
                sell_qty = position

            sell_price = close * (1 - SLIPPAGE_PCT)
            amount = sell_qty * sell_price
            commission = _calc_commission(amount)
            tax = amount * TAX_RATE
            net_proceeds = amount - commission - tax

            # 计算这部分仓位的 PnL
            cost_basis = avg_cost * sell_qty
            pnl = net_proceeds - cost_basis
            closed_trades.append({
                'buy_date': '',  # 简化：不追溯买入日
                'sell_date': date,
                'qty': sell_qty,
                'buy_price': avg_cost,
                'sell_price': sell_price,
                'pnl': pnl,
                'pnl_pct': pnl / cost_basis * 100 if cost_basis else 0,
                'rule_name': signal.rule_name,
            })

            cash += net_proceeds
            position -= sell_qty
            if position == 0:
                avg_cost = 0
            trades.append(Trade(date, 'SELL', sell_qty, sell_price, amount, commission + tax, signal.rule_name, signal.reason))

        equity_curve.append((date, cash + position * close))

    # ===== 收盘清算 =====
    last_close = float(bars.iloc[-1]['close'])
    final_value = cash + position * last_close
    total_return_pct = (final_value - initial_cash) / initial_cash * 100

    # 年化（假设 252 个交易日/年）
    n_days = max(len(equity_curve), 1)
    if n_days > 0:
        annual_return_pct = ((final_value / initial_cash) ** (252 / n_days) - 1) * 100
    else:
        annual_return_pct = 0

    # 最大回撤
    if equity_curve:
        values = pd.Series([v for _, v in equity_curve])
        peak = values.cummax()
        dd = (values - peak) / peak * 100
        max_drawdown_pct = abs(dd.min())
    else:
        max_drawdown_pct = 0

    # 夏普比率（日收益率）
    if len(equity_curve) >= 2:
        values = pd.Series([v for _, v in equity_curve])
        daily_ret = values.pct_change().dropna()
        if daily_ret.std() > 0:
            sharpe_ratio = daily_ret.mean() / daily_ret.std() * np.sqrt(252)
        else:
            sharpe_ratio = 0
    else:
        sharpe_ratio = 0

    # 胜率 + 盈亏比
    if closed_trades:
        wins = [t for t in closed_trades if t['pnl'] > 0]
        losses = [t for t in closed_trades if t['pnl'] <= 0]
        win_rate_pct = len(wins) / len(closed_trades) * 100
        profit_factor = (
            sum(t['pnl'] for t in wins) / abs(sum(t['pnl'] for t in losses))
            if losses and sum(t['pnl'] for t in losses) < 0 else 0
        )
    else:
        win_rate_pct = 0
        profit_factor = 0

    return BacktestResult(
        strategy_id=strategy.strategy_id,
        code=code,
        name=name,
        start_date=str(bars.iloc[0]['date']),
        end_date=str(bars.iloc[-1]['date']),
        bars_count=len(bars),
        initial_cash=initial_cash,
        final_value=final_value,
        final_cash=cash,
        final_position=position,
        total_return_pct=total_return_pct,
        annual_return_pct=annual_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        win_rate_pct=win_rate_pct,
        profit_factor=profit_factor,
        trades=trades,
        equity_curve=equity_curve,
        closed_trades=closed_trades,
    )
