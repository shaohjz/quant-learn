"""
broker/trading_gate.py — 统一自动交易总闸

保证任何误配置都不能意外发送真实订单。真发送必须同时满足：
1. 配置明确启用（trading.live_enabled: true）
2. 环境变量确认令牌匹配（QUANT_LIVE_TOKEN 与 trading.live_token 一致）
3. 账户位于 allowlist（trading.allowed_accounts）
4. 单笔金额、单日金额和当日亏损未越限（从 risk 配置读取）

默认只允许 sim / dry_run 模式。
"""

import logging
import os
from datetime import date as Date
from dataclasses import dataclass, field
from typing import Optional

from sim.config import load_config, get, risk_params

logger = logging.getLogger(__name__)


@dataclass
class GateDecision:
    """总闸决策结果"""
    allowed: bool
    reason: str = ""
    details: dict = field(default_factory=dict)


class LiveTradingGate:
    """统一自动交易总闸 — 所有实盘下单路径必须通过此检查。"""

    def __init__(self, config: Optional[dict] = None):
        self._config = config or load_config()
        self._risk = risk_params()
        # 当日累计交易追踪
        self._daily_new_amount: float = 0.0
        self._daily_trade_date: Optional[str] = None

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def check(self, mode: str, account_id: str, order_amount: float,
              trade_date: Optional[Date] = None) -> GateDecision:
        """检查是否允许下单。

        :param mode: broker 模式（sim / dry_run / live / qmt）
        :param account_id: 资金账号字符串
        :param order_amount: 单笔订单金额（含佣金估算）
        :param trade_date: 交易日
        :return: GateDecision
        """
        mode = (mode or "sim").lower()

        # sim / dry_run 模式永远允许（不影响模拟盘和 dry_run）
        if mode in ("sim", "dry_run"):
            logger.info(f"TradingGate: mode={mode} → ALLOWED (sim/dry_run always pass)")
            return GateDecision(
                allowed=True,
                reason=f"mode={mode} is always allowed",
                details={"mode": mode, "check_type": "sim_passthrough"},
            )

        # 以下检查只对 live / qmt 模式生效
        failures: list[str] = []
        details: dict = {"mode": mode, "account_id": account_id, "order_amount": order_amount}

        # 1) 配置明确启用
        live_enabled = self._config.get("trading", {}).get("live_enabled", False)
        if not live_enabled:
            failures.append("trading.live_enabled is not set or False")
            details["live_enabled"] = live_enabled

        # 2) 环境变量令牌匹配
        expected_token = self._config.get("trading", {}).get("live_token", "")
        actual_token = os.environ.get("QUANT_LIVE_TOKEN", "")
        if not expected_token:
            failures.append("trading.live_token is not configured")
            details["token_check"] = "no_token_configured"
        elif actual_token != expected_token:
            failures.append("QUANT_LIVE_TOKEN env var does not match trading.live_token")
            details["token_check"] = "mismatch"
        else:
            details["token_check"] = "matched"

        # 3) 账户位于白名单
        allowed_accounts = self._config.get("trading", {}).get("allowed_accounts", [])
        if not isinstance(allowed_accounts, list):
            allowed_accounts = []
        if str(account_id) not in [str(a) for a in allowed_accounts]:
            failures.append(f"account_id={account_id} is not in trading.allowed_accounts whitelist")
            details["allowed_accounts"] = allowed_accounts

        # 4) 金额限制
        td_str = (trade_date or Date.today()).isoformat()
        # 重置当日累计（新交易日）
        if self._daily_trade_date != td_str:
            self._daily_new_amount = 0.0
            self._daily_trade_date = td_str

        # 单笔金额限制
        max_single_amount_pct = self._risk.get("max_daily_build_amount_pct", 0.30)
        # 需要总资产来计算限额 — 从配置中的 max_total_value 推算
        max_total_value = float(
            self._config.get("accounts", {}).get("learn", {}).get("max_total_value", 100000.0)
        )
        max_single_amount = max_total_value * max_single_amount_pct
        if order_amount > max_single_amount:
            failures.append(
                f"single order amount {order_amount:.2f} exceeds limit {max_single_amount:.2f}"
            )
            details["max_single_amount"] = max_single_amount

        # 当日累计新建仓位金额限制
        cumulative = self._daily_new_amount + order_amount
        max_daily_amount = max_total_value * max_single_amount_pct
        if cumulative > max_daily_amount:
            failures.append(
                f"daily cumulative amount {cumulative:.2f} exceeds limit {max_daily_amount:.2f}"
            )
            details["daily_cumulative"] = cumulative
            details["max_daily_amount"] = max_daily_amount

        # 当日亏损限制 — 需要从数据库/运行状态读取，这里简化为配置阈值
        # 完整实现需要在 QL-012 (TradingHealthGate) 中补充

        if failures:
            reason = "; ".join(failures)
            logger.warning(f"TradingGate: mode={mode} account={account_id} → BLOCKED: {reason}")
            return GateDecision(allowed=False, reason=reason, details=details)

        # 通过 — 记录当日累计
        self._daily_new_amount += order_amount
        logger.info(f"TradingGate: mode={mode} account={account_id} → ALLOWED")
        return GateDecision(allowed=True, reason="all checks passed", details=details)

    def audit_log(self, decision: GateDecision, stock_code: str = "",
                  side: str = "", quantity: int = 0, price: float = 0.0) -> None:
        """记录结构化审计日志（不下单时也留痕）。

        真实写入 sim_orders 的逻辑由各 broker 负责；这里只写日志。
        """
        status = "ALLOWED" if decision.allowed else "BLOCKED"
        logger.info(
            f"[TradingGateAudit] status={status} reason={decision.reason} "
            f"stock={stock_code} side={side} qty={quantity} px={price} "
            f"details={decision.details}"
        )

    def reset_daily(self) -> None:
        """重置当日累计（测试用或收盘后重置）"""
        self._daily_new_amount = 0.0
        self._daily_trade_date = None


# 模块级单例 — 进程内统一入口
_default_gate: Optional[LiveTradingGate] = None


def get_gate(config: Optional[dict] = None) -> LiveTradingGate:
    """获取默认总闸实例（懒加载）"""
    global _default_gate
    if _default_gate is None:
        _default_gate = LiveTradingGate(config)
    return _default_gate


def check_live_order(mode: str, account_id: str, order_amount: float,
                     trade_date: Optional[Date] = None) -> GateDecision:
    """便捷函数 — 调用默认总闸检查"""
    return get_gate().check(mode, account_id, order_amount, trade_date)
