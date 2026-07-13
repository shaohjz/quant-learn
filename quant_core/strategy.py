"""
quant_core/strategy.py — 无IO的统一策略接口

QL-008: 同一输入在回测、Paper、QMT 生成相同 SignalIntent。

核心接口:
  decide(features, portfolio_state, strategy_config, as_of) -> list[SignalIntent]

- SignalIntent 只描述方向、目标、置信度、理由和生效时间，不直接下单
- 导入和调用策略核心不会访问文件、网络或数据库
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date as Date
from typing import Any, Optional

from .domain import SignalIntent, Direction


@dataclass
class PortfolioState:
    """组合状态 — 传给策略的只读快照"""
    cash: float = 0.0
    total_value: float = 0.0
    positions: dict[str, dict] = field(default_factory=dict)  # {symbol: {qty, avg_cost, ...}}
    max_positions: int = 6
    max_position_pct: float = 0.2
    daily_new_count: int = 0
    max_daily_new: int = 3
    as_of: Optional[Date] = None


class StrategyCore(ABC):
    """策略核心 — 无IO接口

    子类实现 decide() 方法，返回信号意图列表。
    通知、SQLite、网络、交易时段和执行状态机移到外围服务。
    """

    name: str = "abstract"

    @abstractmethod
    def decide(
        self,
        features: dict[str, Any],
        portfolio_state: PortfolioState,
        strategy_config: dict,
        as_of: Date,
    ) -> list[SignalIntent]:
        """生成信号意图

        :param features: 特征数据（由上游时点化数据模块提供）
        :param portfolio_state: 组合状态（只读快照）
        :param strategy_config: 策略配置
        :param as_of: 决策日期（时点化）
        :return: 信号意图列表
        """
        ...


class ThresholdStrategyCore(StrategyCore):
    """阈值策略核心 — 迁移自 threshold_strategy / threshold_alert_strategy

    只包含核心信号逻辑，无IO副作用。
    """

    name = "threshold"

    def decide(
        self,
        features: dict[str, Any],
        portfolio_state: PortfolioState,
        strategy_config: dict,
        as_of: Date,
    ) -> list[SignalIntent]:
        """根据阈值规则生成信号

        features 结构:
          {
            "symbol1": {"price": 10.5, "ma10": 10.6, "ma20": 10.2, ...},
            "symbol2": {...},
          }

        strategy_config 结构:
          {
            "watchlist": {
              "000600": {
                "name": "建投能源",
                "rules": {
                  "buy_zone": {"trigger": 10.17, "dir": "below"},
                  "buy_strong": {"trigger": 9.9, "dir": "below"},
                  "trend_break": {"trigger": 9.26, "dir": "below"},
                },
                "trend_filter": {"status": "HEALTHY", ...},
              }
            }
          }
        """
        signals: list[SignalIntent] = []
        watchlist = strategy_config.get("watchlist", {})

        for symbol, stock_cfg in watchlist.items():
            if not stock_cfg.get("enabled", True):
                continue

            rules = stock_cfg.get("rules", {})
            trend_filter = stock_cfg.get("trend_filter", {})
            trend_status = trend_filter.get("status", "HEALTHY")

            stock_features = features.get(symbol, {})
            current_price = stock_features.get("price", 0)
            if current_price <= 0:
                continue

            for rule_name, rule_cfg in rules.items():
                trigger = rule_cfg.get("trigger", 0)
                direction = rule_cfg.get("dir", "below")
                msg = rule_cfg.get("msg", "")

                triggered = False
                if direction == "below" and current_price <= trigger:
                    triggered = True
                elif direction == "above" and current_price >= trigger:
                    triggered = True

                if not triggered:
                    continue

                # 确定信号方向
                if "buy" in rule_name.lower():
                    signal_direction = Direction.LONG
                elif "trend_break" in rule_name.lower() or "stop" in rule_name.lower():
                    signal_direction = Direction.SHORT
                elif "take_profit" in rule_name.lower():
                    signal_direction = Direction.SHORT
                elif "right_side_confirm" in rule_name.lower():
                    signal_direction = Direction.LONG
                else:
                    signal_direction = Direction.NEUTRAL

                signals.append(SignalIntent(
                    symbol=symbol,
                    direction=signal_direction,
                    confidence=0.7 if "strong" in rule_name else 0.5,
                    reason=f"{rule_name}|{msg}" if msg else rule_name,
                    effective_time=None,  # 由执行层确定
                    target_price=trigger,
                    as_of=as_of,
                    # Point-in-time 阈值信息
                    threshold_effective_from=as_of,
                    threshold_input_end_time=as_of,
                ))

        # 风控过滤
        filtered = self._apply_risk_filters(signals, portfolio_state)
        return filtered

    def _apply_risk_filters(
        self,
        signals: list[SignalIntent],
        portfolio_state: PortfolioState,
    ) -> list[SignalIntent]:
        """应用风险过滤（仓位上限、日频限制等）"""
        buy_signals = [s for s in signals if s.direction == Direction.LONG]
        sell_signals = [s for s in signals if s.direction == Direction.SHORT]
        other_signals = [s for s in signals if s.direction == Direction.NEUTRAL]

        # 买入信号受仓位限制
        current_positions = len(portfolio_state.positions)
        remaining_slots = portfolio_state.max_positions - current_positions
        remaining_daily = portfolio_state.max_daily_new - portfolio_state.daily_new_count

        allowed_buys = buy_signals[:min(remaining_slots, remaining_daily, len(buy_signals))]

        # 卖出信号不受仓位限制
        return allowed_buys + sell_signals + other_signals
