"""Shared helpers for strategy vs non-strategy trade attribution.

Snapshot / live-mirror sync fills contaminate win-rate and expectancy if mixed
into automatic strategy stats. Keep one filter used by closed-trade and signal
performance analytics.
"""
from __future__ import annotations

from typing import Any

# BUY reason / broker markers that are NOT automatic strategy entries.
_NON_STRATEGY_REASON_MARKERS = (
    "初始化建仓快照",
    "同步真实账户",
    "用户真实持仓",
    "user_real_position",
    "live_mirror_init",
    "manual_initial_snapshot",
)
_NON_STRATEGY_BROKERS = {
    "live_mirror",
    "live_mirror_init",
    "live_mirror_sync",
    "real_sync",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def is_non_strategy_entry(
    signal_reason: Any = "",
    broker: Any = "",
    *,
    signal_detail: Any = None,
) -> bool:
    """True when the opening fill should be excluded from strategy expectancy."""
    broker_key = _text(broker).lower()
    if broker_key in _NON_STRATEGY_BROKERS:
        return True

    reason = _text(signal_reason)
    if any(marker in reason for marker in _NON_STRATEGY_REASON_MARKERS):
        return True

    if isinstance(signal_detail, dict):
        source = _text(signal_detail.get("source") or signal_detail.get("source_type")).lower()
        if source in {"manual_initial_snapshot", "user_real_position", "live_mirror"}:
            return True
    return False


def entry_signal_label(signal_reason: Any = "", signal_detail: Any = None) -> str:
    """Stable label for dashboards; snapshot entries collapse to init_snapshot."""
    if is_non_strategy_entry(signal_reason, signal_detail=signal_detail):
        return "init_snapshot"
    reason = _text(signal_reason)
    if not reason:
        return "unknown"
    lower = reason.lower()
    for tag in ("buy_zone", "buy_strong", "buy_weak", "right_confirm", "trend_break_buy"):
        if tag in lower:
            return tag
    # Common "自动: buy_zone | ..." prefix form
    if "buy_zone" in reason:
        return "buy_zone"
    if "buy_strong" in reason:
        return "buy_strong"
    return reason.split("|", 1)[0].strip()[:48] or "unknown"
