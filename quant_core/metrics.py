"""
quant_core/metrics.py — 统一指标计算

QL-009: 替代"每只股票独立资金再平均"的不可投资 leaderboard。
核心指标: CAGR、波动、Sharpe、Sortino、Calmar、最大回撤、超额收益。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class PerformanceMetrics:
    """绩效指标"""
    total_return: float = 0.0
    cagr: float = 0.0
    annual_volatility: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    net_expectancy: float = 0.0       # 核心目标
    total_trades: int = 0
    benchmark_return: float = 0.0
    excess_return: float = 0.0
    information_ratio: float = 0.0
    beta: float = 0.0
    turnover: float = 0.0
    total_fees: float = 0.0


def calc_max_drawdown(nav_series: list[float]) -> float:
    """计算最大回撤"""
    if not nav_series:
        return 0.0
    peak = nav_series[0]
    max_dd = 0.0
    for nav in nav_series:
        if nav > peak:
            peak = nav
        if peak > 0:
            dd = (peak - nav) / peak
            max_dd = max(max_dd, dd)
    return max_dd


def calc_sharpe(returns: list[float], risk_free_rate: float = 0.02) -> float:
    """计算 Sharpe Ratio（年化）"""
    if len(returns) < 2:
        return 0.0
    mean_ret = sum(returns) / len(returns)
    variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return 0.0
    # 年化: 假设日频 returns
    annualized_mean = mean_ret * 252
    annualized_std = std * math.sqrt(252)
    return (annualized_mean - risk_free_rate) / annualized_std


def calc_sortino(returns: list[float], risk_free_rate: float = 0.02,
                 target: float = 0.0) -> float:
    """计算 Sortino Ratio（年化，只考虑下行波动）"""
    if len(returns) < 2:
        return 0.0
    mean_ret = sum(returns) / len(returns)
    downside = [min(r - target, 0) ** 2 for r in returns]
    downside_var = sum(downside) / len(downside)
    downside_std = math.sqrt(downside_var) if downside_var > 0 else 0.0
    if downside_std == 0:
        return 0.0
    annualized_mean = mean_ret * 252
    annualized_downside_std = downside_std * math.sqrt(252)
    return (annualized_mean - risk_free_rate) / annualized_downside_std


def calc_net_expectancy(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    fees: float = 0.0,
    slippage: float = 0.0,
    market_impact: float = 0.0,
) -> float:
    """计算净期望值 — 核心目标

    Net Expectancy = P(win) × AvgWin - P(loss) × AvgLoss - Fees - Slippage - Impact
    高胜率但平均亏损远大于平均盈利的策略仍应淘汰。
    """
    loss_rate = 1.0 - win_rate
    gross = win_rate * avg_win - loss_rate * abs(avg_loss)
    return gross - fees - slippage - market_impact


def calc_excess_return(portfolio_return: float, benchmark_return: float) -> float:
    """计算超额收益"""
    return portfolio_return - benchmark_return


def calc_information_ratio(
    excess_returns: list[float],
) -> float:
    """计算 Information Ratio"""
    if len(excess_returns) < 2:
        return 0.0
    mean_excess = sum(excess_returns) / len(excess_returns)
    variance = sum((r - mean_excess) ** 2 for r in excess_returns) / (len(excess_returns) - 1)
    tracking_error = math.sqrt(variance * 252) if variance > 0 else 0.0
    if tracking_error == 0:
        return 0.0
    return (mean_excess * 252) / tracking_error
