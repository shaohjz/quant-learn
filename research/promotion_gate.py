"""
research/promotion_gate.py — Paper → 小额 → 放量晋级门槛

QL-014: 用可观测的真实执行偏差决定是否放量，而不是凭一次回测。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date as Date
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PromotionEvidence:
    """晋级证据快照"""
    strategy_name: str
    # 数据
    data_hash: str = ""
    config_hash: str = ""
    no_future_data_violations: bool = True
    data_staleness_rate: float = 0.0
    # 研究
    num_market_regimes_covered: int = 0
    num_closed_trades: int = 0
    oos_positive_windows_pct: float = 0.0
    net_expectancy_2x_cost: float = 0.0
    single_stock_dominance: bool = False
    single_month_dominance: bool = False
    # Paper
    paper_trading_days: int = 0
    signal_consistency_rate: float = 0.0
    execution_deviation: float = 0.0
    rejection_rate: float = 0.0
    max_drawdown_breached: bool = False
    oms_reconciliation_clean: bool = True
    # 综合
    can_promote: bool = False
    block_reasons: list[str] = field(default_factory=list)


# 晋级阈值（可配置）
MIN_MARKET_REGIMES = 3
MIN_CLOSED_TRADES = 100        # 建议至少100笔
MIN_OOS_POSITIVE_WINDOWS = 0.5  # 多数窗口正超额
MIN_PAPER_DAYS = 60
MIN_SIGNAL_CONSISTENCY = 0.9
MAX_EXECUTION_DEVIATION = 0.02
MAX_REJECTION_RATE = 0.1


class PromotionGate:
    """晋级门控 — 机器可读规则，不允许手工跳过P0门槛"""

    def evaluate(self, evidence: PromotionEvidence) -> PromotionEvidence:
        """评估是否满足晋级条件"""
        reasons: list[str] = []

        # ─── 数据门槛 ───
        if not evidence.no_future_data_violations:
            reasons.append("存在未来数据违规")
        if evidence.data_staleness_rate > 0:
            reasons.append(f"行情陈旧率 {evidence.data_staleness_rate:.2%} > 0")

        # ─── 研究门槛 ───
        if evidence.num_market_regimes_covered < MIN_MARKET_REGIMES:
            reasons.append(
                f"市场状态覆盖不足: {evidence.num_market_regimes_covered} < {MIN_MARKET_REGIMES}"
            )
        if evidence.num_closed_trades < MIN_CLOSED_TRADES:
            reasons.append(
                f"已平仓交易不足: {evidence.num_closed_trades} < {MIN_CLOSED_TRADES}（标记证据不足）"
            )
        if evidence.oos_positive_windows_pct < MIN_OOS_POSITIVE_WINDOWS:
            reasons.append(
                f"OOS正超额窗口不足: {evidence.oos_positive_windows_pct:.0%} < {MIN_OOS_POSITIVE_WINDOWS:.0%}"
            )
        if evidence.net_expectancy_2x_cost <= 0:
            reasons.append("2倍成本压力下净期望非正")
        if evidence.single_stock_dominance:
            reasons.append("收益由单一股票主导")
        if evidence.single_month_dominance:
            reasons.append("收益由单月份主导")

        # ─── Paper门槛 ───
        if evidence.paper_trading_days < MIN_PAPER_DAYS:
            reasons.append(
                f"Paper运行天数不足: {evidence.paper_trading_days} < {MIN_PAPER_DAYS}"
            )
        if evidence.signal_consistency_rate < MIN_SIGNAL_CONSISTENCY:
            reasons.append(
                f"信号一致率不足: {evidence.signal_consistency_rate:.0%} < {MIN_SIGNAL_CONSISTENCY:.0%}"
            )
        if evidence.execution_deviation > MAX_EXECUTION_DEVIATION:
            reasons.append(
                f"执行偏差过大: {evidence.execution_deviation:.2%} > {MAX_EXECUTION_DEVIATION:.2%}"
            )
        if evidence.rejection_rate > MAX_REJECTION_RATE:
            reasons.append(
                f"拒单率过高: {evidence.rejection_rate:.2%} > {MAX_REJECTION_RATE:.2%}"
            )
        if evidence.max_drawdown_breached:
            reasons.append("最大回撤突破预设风险预算")
        if not evidence.oms_reconciliation_clean:
            reasons.append("OMS每日对账存在未解释差异")

        evidence.block_reasons = reasons
        evidence.can_promote = len(reasons) == 0

        if evidence.can_promote:
            logger.info(f"✅ {evidence.strategy_name} 满足晋级门槛")
        else:
            logger.warning(f"⛔ {evidence.strategy_name} 不满足晋级门槛: {reasons}")

        return evidence
