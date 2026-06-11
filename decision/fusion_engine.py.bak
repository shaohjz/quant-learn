"""
decision/fusion_engine.py — 双账户融合决策器（v1）

输入：
  - qlib_signal: dict | None  从 daily_signals.json 取的当前股票信号
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
  confidence      : 0.0 ~ 1.0

决策规则（v1）：
  ┌──────────────────────────┬─────────────────────────┬───────────────┐
  │ threshold_alert.level    │ qlib_signal.action      │ 决策          │
  ├──────────────────────────┼─────────────────────────┼───────────────┤
  │ stop_loss / hard_stop /  │ SELL / HOLD / None      │ 强卖出        │
  │ deep_drop / limitdown_*  │                         │ (执行老规则)  │
  ├──────────────────────────┼─────────────────────────┼───────────────┤
  │ stop_loss(任一)         │ BUY                     │ HOLD（冲突，  │
  │                          │                         │ 优先止损）    │
  ├──────────────────────────┼─────────────────────────┼───────────────┤
  │ buy_zone / buy_strong    │ BUY                     │ 买入          │
  ├──────────────────────────┼─────────────────────────┼───────────────┤
  │ buy_zone / buy_strong    │ SELL                    │ HOLD          │
  │                          │                         │ (AI 看空)     │
  ├──────────────────────────┼─────────────────────────┼───────────────┤
  │ take_profit / half_out / │ BUY / HOLD              │ HOLD          │
  │ rebound_exit             │                         │ (AI 不看空时  │
  │                          │                         │  暂不止盈)    │
  ├──────────────────────────┼─────────────────────────┼───────────────┤
  │ take_profit              │ SELL                    │ 卖出          │
  ├──────────────────────────┼─────────────────────────┼───────────────┤
  │ None                     │ BUY (高 conf > 0.6)     │ 买入          │
  ├──────────────────────────┼─────────────────────────┼───────────────┤
  │ None                     │ BUY (低 conf <= 0.6)    │ HOLD          │
  ├──────────────────────────┼─────────────────────────┼───────────────┤
  │ None                     │ SELL (高 conf > 0.6) +  │ 卖出          │
  │                          │ position_qty > 0        │               │
  ├──────────────────────────┼─────────────────────────┼───────────────┤
  │ None                     │ SELL + position_qty=0   │ HOLD（无仓位  │
  │                          │                         │  不开空）     │
  └──────────────────────────┴─────────────────────────┴───────────────┘
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


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
    """融合决策结果"""
    stock_code: str
    action: str                 # "BUY" / "SELL" / "HOLD"
    target_account: str         # "qmt_sim" / "real_advisor" / "none"
    qty: int = 0
    price: float = 0.0
    reason: str = ""
    confidence: float = 0.0
    rule: str = ""              # 命中了哪条规则
    sources: dict = field(default_factory=dict)  # 调试用：原始 qlib + alert

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
    融合决策。详见模块 docstring。

    :param stock_code: 6 位股票代码（如 "600330"）
    :param current_price: 当前现价
    :param position_qty: 当前账户持仓数量（QMT 或镜像）
    :param qlib_signal: 从 daily_signals.json["signals"] 中匹配到的 dict，可能 None
    :param threshold_alert: 命中的 portfolio_alert rule（含 level/dir/trigger 等），可能 None
    :return: Decision
    """
    # ---------- 选目标账户 ----------
    # 持仓 5 只 → real_advisor（只推送，不下到 QMT）
    # 其它 → qmt_sim
    target = "real_advisor" if _is_holding(stock_code) else "qmt_sim"

    sources = {
        "has_qlib": qlib_signal is not None,
        "has_alert": threshold_alert is not None,
        "in_holdings": _is_holding(stock_code),
    }

    qlib_action = (qlib_signal or {}).get("action") if qlib_signal else None
    qlib_conf = float((qlib_signal or {}).get("confidence", 0)) if qlib_signal else 0.0
    alert_level = (threshold_alert or {}).get("level") if threshold_alert else None

    # ============ 规则 1：止损/深跌（最高优先级，无视 qlib） ============
    if alert_level in SELL_LEVELS:
        # 必须有持仓才能卖
        if position_qty <= 0:
            # 不在持仓的股票被触发跌幅警报（不太可能，但兜底）
            return Decision(
                stock_code=stock_code, action="HOLD", target_account=target,
                reason=f"触发 {alert_level} 但无持仓，忽略",
                rule="SELL_NO_POSITION",
                sources=sources,
            )
        if qlib_action == "BUY":
            # AI 看多但价格已破止损 → 优先止损（资金安全 > AI 预测）
            return Decision(
                stock_code=stock_code, action="SELL", target_account=target,
                qty=_round_lot(position_qty), price=current_price,
                reason=f"触发 {alert_level}（强制止损）；AI 虽看多但保资金优先",
                confidence=0.9,
                rule="STOP_LOSS_OVERRIDE_AI_BUY",
                sources=sources,
            )
        # 默认：止损全部卖
        return Decision(
            stock_code=stock_code, action="SELL", target_account=target,
            qty=_round_lot(position_qty), price=current_price,
            reason=f"触发 {alert_level} ({(threshold_alert or {}).get('message','')})",
            confidence=max(0.85, qlib_conf if qlib_action == "SELL" else 0.85),
            rule="STOP_LOSS",
            sources=sources,
        )

    # ============ 规则 2：止盈 ============
    if alert_level in TAKE_PROFIT_LEVELS:
        if position_qty <= 0:
            return Decision(stock_code=stock_code, action="HOLD",
                            target_account=target, reason="触发止盈但无持仓",
                            rule="TP_NO_POSITION", sources=sources)
        if qlib_action == "SELL":
            return Decision(
                stock_code=stock_code, action="SELL", target_account=target,
                qty=_round_lot(position_qty), price=current_price,
                reason=f"触发 {alert_level} + AI 也看空 → 清仓",
                confidence=max(0.85, qlib_conf), rule="TAKE_PROFIT_AI_AGREE",
                sources=sources,
            )
        # AI 不看空就先暂时不全卖
        return Decision(
            stock_code=stock_code, action="HOLD", target_account=target,
            reason=f"触发 {alert_level} 但 AI 仍看 {qlib_action or '未知'}，暂不止盈",
            rule="TP_AI_DISAGREE", sources=sources,
        )

    # ============ 规则 3：减仓 ============
    if alert_level in TRIM_LEVELS:
        if position_qty <= 0:
            return Decision(stock_code=stock_code, action="HOLD",
                            target_account=target, reason="触发减仓但无持仓",
                            rule="TRIM_NO_POSITION", sources=sources)
        if qlib_action == "SELL":
            qty = _round_lot(position_qty // 2 or 100)
            return Decision(
                stock_code=stock_code, action="SELL", target_account=target,
                qty=qty, price=current_price,
                reason=f"触发 {alert_level} + AI 看空 → 减一半",
                confidence=max(0.7, qlib_conf), rule="TRIM_AI_AGREE",
                sources=sources,
            )
        return Decision(
            stock_code=stock_code, action="HOLD", target_account=target,
            reason=f"触发 {alert_level} 但 AI 看 {qlib_action or '未知'}，暂不减仓",
            rule="TRIM_AI_DISAGREE", sources=sources,
        )

    # ============ 规则 4：买入区 ============
    if alert_level in BUY_LEVELS:
        if qlib_action == "SELL":
            return Decision(
                stock_code=stock_code, action="HOLD", target_account=target,
                reason=f"价位进入 {alert_level} 但 AI 看空 → 观望",
                rule="BUY_ZONE_AI_DISAGREE", confidence=qlib_conf,
                sources=sources,
            )
        if qlib_action == "BUY":
            qty = _suggest_buy_qty(current_price, level=alert_level)
            return Decision(
                stock_code=stock_code, action="BUY", target_account=target,
                qty=qty, price=current_price,
                reason=f"价位进入 {alert_level} + AI 看多 → 建仓",
                confidence=max(0.75, qlib_conf), rule="BUY_ZONE_AI_AGREE",
                sources=sources,
            )
        # 没 qlib 信号或 HOLD → 走老规则（按 portfolio_alert 原意买入）
        qty = _suggest_buy_qty(current_price, level=alert_level)
        return Decision(
            stock_code=stock_code, action="BUY", target_account=target,
            qty=qty, price=current_price,
            reason=f"价位进入 {alert_level}（无 AI 信号，按原规则）",
            confidence=0.55, rule="BUY_ZONE_NO_AI",
            sources=sources,
        )

    # ============ 规则 5：仅有 qlib，无 alert ============
    if qlib_action == "BUY" and qlib_conf > 0.60:
        if position_qty > 0:
            # 已经有仓位，再加仓更保守
            return Decision(stock_code=stock_code, action="HOLD", target_account=target,
                            reason=f"AI BUY conf={qlib_conf:.2f} 但已有持仓 {position_qty}，等回调",
                            confidence=qlib_conf, rule="QLIB_BUY_HAS_POS",
                            sources=sources)
        qty = _suggest_buy_qty(current_price)
        return Decision(
            stock_code=stock_code, action="BUY", target_account=target,
            qty=qty, price=current_price,
            reason=f"AI BUY conf={qlib_conf:.2f}（CSI300 排名靠前）",
            confidence=qlib_conf, rule="QLIB_BUY_HIGH_CONF",
            sources=sources,
        )

    if qlib_action == "SELL" and qlib_conf > 0.60 and position_qty > 0:
        return Decision(
            stock_code=stock_code, action="SELL", target_account=target,
            qty=_round_lot(position_qty), price=current_price,
            reason=f"AI SELL conf={qlib_conf:.2f}，清仓",
            confidence=qlib_conf, rule="QLIB_SELL_HIGH_CONF",
            sources=sources,
        )

    if qlib_action == "BUY" and qlib_conf <= 0.60:
        return Decision(stock_code=stock_code, action="HOLD", target_account=target,
                        reason=f"AI BUY 但 conf={qlib_conf:.2f} 较低，观望",
                        confidence=qlib_conf, rule="QLIB_BUY_LOW_CONF",
                        sources=sources)

    if qlib_action == "SELL" and position_qty == 0:
        return Decision(stock_code=stock_code, action="HOLD", target_account=target,
                        reason="AI SELL 但无持仓（A 股不开空）",
                        confidence=qlib_conf, rule="QLIB_SELL_NO_POS",
                        sources=sources)

    # ============ 兜底 ============
    return Decision(
        stock_code=stock_code, action="HOLD", target_account=target,
        reason=f"无明确信号 (alert={alert_level} qlib={qlib_action})",
        confidence=qlib_conf, rule="DEFAULT_HOLD",
        sources=sources,
    )
