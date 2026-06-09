"""sim/cash_warning.py — REQ-045: 现金过低预警 + 仓位管理优化

背景
----
当前现金占比约 1.6%（18634 / 22529），接近满仓状态。
一旦出现新的买入信号，资金不足以建仓；极端行情下也缺乏补仓/调仓弹性。

本模块提供：
  1) ``check_cash_ratio``  —— 检查现金占比，返回预警等级和建议
  2) ``suggest_position_size``  —— 基于现金占比优化建议买入数量
  3) ``format_cash_warning``  —— 格式化预警消息（用于告警/日志）

设计原则：
  - 纯函数，便于测试
  - 不依赖全局变量，显式传入参数
  - 预警不阻断交易（仅建议），但 cash_pct < min 时禁止新建仓
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CashWarning:
    """现金占比检查结果"""
    cash: float
    total_value: float
    cash_pct: float          # 现金占比 (0~1)
    level: str               # "ok" | "low" | "critical"
    message: str
    can_buy: bool            # 是否允许新建仓
    suggested_qty_reduction: float  # 建议买入数量缩减比例 (0~1), 1.0 = 完全不买


# 阈值常量
CASH_PCT_LOW = 0.10        # 现金占比 < 10% 触发 low 告警
CASH_PCT_CRITICAL = 0.05   # 现金占比 < 5% 触发 critical 告警，禁止新建仓
CASH_PCT_MIN_NEW = 0.08    # 现金占比 < 8% 禁止新建仓（仅允许加仓）


def check_cash_ratio(cash: float, total_value: float,
                     cash_pct_low: float = CASH_PCT_LOW,
                     cash_pct_critical: float = CASH_PCT_CRITICAL,
                     cash_pct_min_new: float = CASH_PCT_MIN_NEW) -> CashWarning:
    """检查现金占比，返回预警等级和操作建议。

    等级判定：
      - ok:       cash_pct >= 10%，正常
      - low:      5% <= cash_pct < 10%，告警，建议缩减仓位
      - critical: cash_pct < 5%，严重告警，禁止新建仓
    """
    if total_value <= 0:
        return CashWarning(
            cash=cash, total_value=total_value, cash_pct=0.0,
            level="critical", message="总资产为0，无法计算现金占比",
            can_buy=False, suggested_qty_reduction=1.0,
        )

    cash_pct = cash / total_value

    if cash_pct < cash_pct_critical:
        return CashWarning(
            cash=cash, total_value=total_value, cash_pct=cash_pct,
            level="critical",
            message=f"⚠️ 现金占比 {cash_pct:.1%} 严重过低（< {cash_pct_critical:.0%}），"
                    f"禁止新建仓！可用 ¥{cash:,.0f} / 总资产 ¥{total_value:,.0f}",
            can_buy=False,
            suggested_qty_reduction=1.0,
        )

    if cash_pct < cash_pct_low:
        # 计算缩减比例：cash_pct 越低，缩减越多
        # low=10%, critical=5% 之间线性插值
        reduction = 1.0 - (cash_pct - cash_pct_critical) / (cash_pct_low - cash_pct_critical)
        reduction = max(0.3, min(1.0, reduction))  # 至少缩减 30%

        can_buy_new = cash_pct >= cash_pct_min_new

        return CashWarning(
            cash=cash, total_value=total_value, cash_pct=cash_pct,
            level="low",
            message=f"⚡ 现金占比 {cash_pct:.1%} 偏低（< {cash_pct_low:.0%}），"
                    f"建议缩减买入量 {reduction:.0%}。"
                    f"{'允许' if can_buy_new else '禁止'}新建仓。"
                    f"可用 ¥{cash:,.0f} / 总资产 ¥{total_value:,.0f}",
            can_buy=can_buy_new,
            suggested_qty_reduction=reduction,
        )

    return CashWarning(
        cash=cash, total_value=total_value, cash_pct=cash_pct,
        level="ok",
        message=f"✅ 现金占比 {cash_pct:.1%} 正常。"
                f"可用 ¥{cash:,.0f} / 总资产 ¥{total_value:,.0f}",
        can_buy=True,
        suggested_qty_reduction=0.0,
    )


def suggest_position_size(desired_qty: int, warning: CashWarning) -> int:
    """根据现金预警等级建议调整买入数量。

    - ok: 不缩减
    - low: 按比例缩减（向下取整到100股）
    - critical: 返回 0
    """
    if warning.level == "critical":
        return 0
    if warning.level == "low" and warning.suggested_qty_reduction > 0:
        # 缩减：desired_qty * (1 - reduction)
        adjusted = int(desired_qty * (1.0 - warning.suggested_qty_reduction))
        # 向下取整到100股
        adjusted = (adjusted // 100) * 100
        return adjusted
    return desired_qty


def format_cash_warning(warning: CashWarning) -> str:
    """格式化预警消息（用于日志/企微告警）。"""
    prefix = {
        "ok": "💰",
        "low": "⚡",
        "critical": "🚨",
    }.get(warning.level, "")
    return f"{prefix} {warning.message}"


def check_and_warn(cash: float, total_value: float) -> CashWarning:
    """便捷函数：检查现金占比并记录日志。"""
    warning = check_cash_ratio(cash, total_value)
    if warning.level == "critical":
        logger.critical(warning.message)
    elif warning.level == "low":
        logger.warning(warning.message)
    else:
        logger.debug(warning.message)
    return warning
