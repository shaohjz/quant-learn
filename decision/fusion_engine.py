"""decision/fusion_engine.py — 双账户融合决策器（v2 · REQ-042 去大模型化）

REQ-042 去大模型化说明：
  - ❌ 不再接受 qlib_signal（AI 信号 / daily_signals.json）作为输入
  - ✅ 纯代码规则：threshold_alert（阈值触发）+ 持仓状态 + 当前价格
  - ✅ 决策结果通过企微 Webhook 直推（由调用方 fusion_strategy.py / portfolio_alert.py 执行推送）
  - ✅ qlib_signal 参数保留（兼容旧接口），但忽略其 action/confidence

输入：
  - threshold_alert: dict | None  portfolio_alert 当日触发的阈值（来自 alert_state.json）
  - position_qty: int  当前 broker 账户该股持仓数量（QMT 模拟账户：可能 0）
  - current_price: float  当前现价

输出：
  Decision(action, target_account, qty, reason, confidence)

  action          : BUY / SELL / HOLD
  target_account  : "qmt_sim" / "real_advisor"
                    - qmt_sim     —— 应推到 QMT 模拟账户（dry_run 模式只 print）
                    - real_advisor —— 仅以企微消息推给人工（影响真实账户的建议）
  qty             : 建议数量（100 整数倍）
  reason          : 文字解释，写到日志/推送
  confidence      : 0.0 ~ 1.0  （纯代码规则赋置信度，不再依赖 AI）

决策规则（v2 · 去大模型化版）：
  ┌──────────────────────────┬──────────────────┬───────────────┐
  │ threshold_alert.level    │ 持仓状态         │ 决策          │
  ├──────────────────────────┼──────────────────┼───────────────┤
  │ stop_loss / hard_stop /  │ 有持仓           │ 强卖出        │
  │ deep_drop / limitdown_*  │                  │ (执行止损)    │
  ├──────────────────────────┼──────────────────┼───────────────┤
  │ take_profit / half_out / │ 有持仓           │ 止盈/减仓    │
  │ rebound_exit             │                  │               │
  ├──────────────────────────┼──────────────────┼───────────────┤
  │ buy_zone / buy_strong    │ 无持仓           │ 买入          │
  └──────────────────────────┴──────────────────┴───────────────┘
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

try:
    from sim.config import load_config
    _HAS_CONFIG = True
except Exception:  # noqa: BLE001
    _HAS_CONFIG = False


# 持仓 5 只（决策器自己也认下，避免上游忘传）
HOLDINGS = {"600330", "002256", "002453", "002342", "603601"}

# 卖出/止损相关 level（触发即考虑卖出）
SELL_LEVELS = {
    "stop_loss", "stop_loss_tight", "hard_stop",
    "deep_drop", "limitdown_open", "trend_break",
}
# 减仓 / 部分止盈
TRIM_LEVELS = {"half_out", "rebound_exit", "yc_exit", "take_profit_half"}
# 完全止盈
TAKE_PROFIT_LEVELS = {"take_profit"}
# 买入区
BUY_LEVELS = {"buy_zone", "buy_strong", "support_1", "support_2", "support_3"}


@dataclass
class Decision:
    """融合决策结果（REQ-042 去大模型化）"""
    stock_code: str
    action: str                 # "BUY" / "SELL" / "HOLD"
    target_account: str         # "qmt_sim" / "real_advisor" / "none"
    qty: int = 0
    price: float = 0.0
    reason: str = ""
    confidence: float = 0.0
    rule: str = ""              # 命中了哪条规则
    sources: dict = field(default_factory=dict)  # 调试用

    def is_actionable(self) -> bool:
        return self.action in ("BUY", "SELL") and self.qty > 0


def _round_lot(qty: int) -> int:
    """A 股 100 股整数倍"""
    if qty <= 0:
        return 0
    return (qty // 100) * 100


def _suggest_buy_qty(price: float, target_amount: float = 50_000.0, level: str = None) -> int:
    """按目标金额估算买入手数（默认 5 万元，至少 100 股）。
    支持根据支撑位级别动态分配仓位：
    - support_1: 30% 仓位 (默认 15000)
    - support_2: 60% 仓位 (默认 30000)
    - support_3: 100% 仓位 (默认 50000)
    """
    if price <= 0:
        return 0

    actual_target = target_amount
    if level == "support_1":
        actual_target = target_amount * 0.3
    elif level == "support_2":
        actual_target = target_amount * 0.6
    elif level == "support_3":
        actual_target = target_amount * 1.0

    qty = _round_lot(int(actual_target / price))
    # 如果价格太高导致 round 到 0，至少买1手（100股）
    if qty == 0 and price * 100 <= actual_target * 6:
        qty = 100
    return qty


def _is_holding(stock_code: str) -> bool:
    return stock_code in HOLDINGS


def decide(stock_code: str,
           current_price: float,
           position_qty: int = 0,
           qlib_signal: Optional[dict] = None,
           threshold_alert: Optional[dict] = None) -> Decision:
    """
    融合决策（REQ-042 去大模型化版）。

    ❌ 忽略 qlib_signal（AI 信号），纯代码规则决策。
    ✅ 完全基于 threshold_alert（阈值触发）+ 持仓状态 + 当前价格。

    :param stock_code: 6 位股票代码（如 "600330"）
    :param current_price: 当前现价
    :param position_qty: 当前账户持仓数量（QMT 或镜像）
    :param qlib_signal: 【已废弃】从 daily_signals.json 取的信号（REQ-042 忽略）
    :param threshold_alert: 命中的 portfolio_alert rule（含 level/dir/trigger 等），可能 None
    :return: Decision
    """
    # ---------- 选目标账户 ----------
    # 持仓 5 只 → real_advisor（只推送，不下到 QMT）
    # 其它 → qmt_sim
    target = "real_advisor" if _is_holding(stock_code) else "qmt_sim"

    sources = {
        "has_qlib": False,  # REQ-042: 始终为 False
        "has_alert": threshold_alert is not None,
        "in_holdings": _is_holding(stock_code),
    }

    # REQ-042 去大模型化：忽略 qlib_signal，始终按纯代码规则决策
    # 保留变量读取以便日志输出，但不影响决策
    qlib_action = None  # 不再使用 AI 信号方向
    qlib_conf = 0.0
    alert_level = (threshold_alert or {}).get("level") if threshold_alert else None

    # ============ 规则 1：止损/深跌（最高优先级） ============
    if alert_level in SELL_LEVELS:
        # 必须有持仓才能卖
        if position_qty <= 0:
            return Decision(
                stock_code=stock_code, action="HOLD", target_account=target,
                reason=f"触发 {alert_level} 但无持仓，忽略",
                rule="SELL_NO_POSITION",
                sources=sources,
            )
        # 默认：止损全部卖（纯代码规则，不依赖 AI 信号）
        return Decision(
            stock_code=stock_code, action="SELL", target_account=target,
            qty=_round_lot(position_qty), price=current_price,
            reason=f"触发 {alert_level} ({(threshold_alert or {}).get('message','')})",
            confidence=0.90,  # 止损规则置信度固定 0.90
            rule="STOP_LOSS",
            sources=sources,
        )

    # ============ 规则 2：止盈 ============
    if alert_level in TAKE_PROFIT_LEVELS:
        if position_qty <= 0:
            return Decision(stock_code=stock_code, action="HOLD",
                            target_account=target, reason="触发止盈但无持仓",
                            rule="TP_NO_POSITION", sources=sources)
        # REQ-042：无 AI 信号时，默认执行止盈清仓（纯代码规则）
        return Decision(
            stock_code=stock_code, action="SELL", target_account=target,
            qty=_round_lot(position_qty), price=current_price,
            reason=f"触发 {alert_level}（去大模型化，执行止盈清仓）",
            confidence=0.90,
            rule="TAKE_PROFIT_PURE_CODE",
            sources=sources,
        )

    # ============ 规则 3：减仓 ============
    if alert_level in TRIM_LEVELS:
        if position_qty <= 0:
            return Decision(stock_code=stock_code, action="HOLD",
                            target_account=target, reason="触发减仓但无持仓",
                            rule="TRIM_NO_POSITION", sources=sources)
        # REQ-042：无 AI 信号时，默认减仓一半
        qty = _round_lot(position_qty // 2 or 100)
        return Decision(
            stock_code=stock_code, action="SELL", target_account=target,
            qty=qty, price=current_price,
            reason=f"触发 {alert_level}（去大模型化，减仓一半）",
            confidence=0.80,
            rule="TRIM_PURE_CODE",
            sources=sources,
        )

    # ============ 规则 4：买入区（REQ-042 去大模型化）============
    if alert_level in BUY_LEVELS:
        # REQ-042：不再等待 AI 信号确认，直接按阈值规则买入
        qty = _suggest_buy_qty(current_price, level=alert_level)
        if qty <= 0:
            return Decision(stock_code=stock_code, action="HOLD", target_account=target,
                            reason=f"价位进入 {alert_level} 但计算仓位为 0，跳过",
                            rule="BUY_ZONE_ZERO_QTY", sources=sources)
        return Decision(
            stock_code=stock_code, action="BUY", target_account=target,
            qty=qty, price=current_price,
            reason=f"价位进入 {alert_level}（去大模型化，纯代码规则直接建仓）",
            confidence=0.75,  # 阈值规则固定置信度
            rule="BUY_ZONE_PURE_CODE",
            sources=sources,
        )

    # ============ 规则 5（原）：仅有 qlib，无 alert ============
    # REQ-042 去大模型化：不再有 qlib_signal，此分支改为：
    #   无阈值触发 + 无 AI 信号 → 直接 HOLD
    # 保留分支结构以便将来必要时恢复 AI 信号
    if False:  # pylint: disable=condition-always-false  # 已禁用 AI 信号分支
        pass

    # ============ 兜底（REQ-042 去大模型化）============
    return Decision(
        stock_code=stock_code, action="HOLD", target_account=target,
        reason=f"无明确信号 (alert={alert_level}, AI信号已禁用)",
        confidence=0.50,
        rule="DEFAULT_HOLD",
        sources=sources,
    )
