"""中长线时钟（horizon）配置。

生产与回测共用这一份参数。``enabled=false`` 时所有调用方必须走旧的
MA10/MA20 日线波段，保证测试与回滚行为不变。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class HorizonParams:
    enabled: bool = False
    style: str = "mean_revert"  # mean_revert | trend_pullback
    stop_loss_pct: float = 0.12
    take_profit_pct: float = 0.20
    min_hold_days: int = 15
    rsi_buy: float = 40.0
    near_low60_pct: float = 0.05
    ma60_buy_band: float = 0.02
    ma20_pullback_band: float = 0.02
    ma120_floor: float | None = 0.90
    weekly_only: bool = False
    sell_on_ma60_recover: bool = True
    sell_ma60_band: float = 0.02
    trend_break_ma60: bool = True
    max_positions: int = 3
    single_budget: float = 10_000.0
    max_daily_new_positions: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "style": self.style,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "min_hold_days": self.min_hold_days,
            "rsi_buy": self.rsi_buy,
            "near_low60_pct": self.near_low60_pct,
            "ma60_buy_band": self.ma60_buy_band,
            "ma20_pullback_band": self.ma20_pullback_band,
            "ma120_floor": self.ma120_floor,
            "weekly_only": self.weekly_only,
            "sell_on_ma60_recover": self.sell_on_ma60_recover,
            "sell_ma60_band": self.sell_ma60_band,
            "trend_break_ma60": self.trend_break_ma60,
            "max_positions": self.max_positions,
            "single_budget": self.single_budget,
            "max_daily_new_positions": self.max_daily_new_positions,
        }


_ACCOUNT_DEFAULTS: dict[int, dict[str, Any]] = {
    1: {
        "style": "mean_revert",
        "min_hold_days": 15,
        "max_positions": 5,
        "single_budget": 15_000.0,
    },
    3: {
        "style": "trend_pullback",
        "min_hold_days": 10,
        "max_positions": 3,
        "single_budget": 15_000.0,
        "rsi_buy": 50.0,
        "sell_on_ma60_recover": False,
    },
    4: {
        "style": "mean_revert",
        "min_hold_days": 20,
        "max_positions": 3,
        "single_budget": 8_000.0,
        "weekly_only": True,
    },
}


def _read_config(config: dict | None = None) -> dict:
    if config is not None:
        return config
    path = _PROJECT_ROOT / "config.yaml"
    if yaml is None or not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def load_horizon(account_id: int | None = None, config: dict | None = None) -> HorizonParams:
    """加载全局 horizon，并按账户覆盖。"""

    tree = _read_config(config)
    raw = dict(tree.get("horizon") or {})
    enabled = bool(raw.get("enabled", False))
    accounts = raw.pop("accounts", {}) or {}
    raw.pop("enabled", None)

    merged: dict[str, Any] = {}
    if account_id is not None:
        merged.update(_ACCOUNT_DEFAULTS.get(int(account_id), {}))
    merged.update({k: v for k, v in raw.items() if v is not None})
    if account_id is not None:
        overlay = accounts.get(str(account_id)) or accounts.get(int(account_id)) or {}
        if isinstance(overlay, dict):
            merged.update({k: v for k, v in overlay.items() if v is not None})

    floor = merged.get("ma120_floor", 0.90)
    if floor in (None, False, 0, 0.0):
        floor = None
    else:
        floor = float(floor)

    return HorizonParams(
        enabled=enabled,
        style=str(merged.get("style", "mean_revert")),
        stop_loss_pct=float(merged.get("stop_loss_pct", 0.12)),
        take_profit_pct=float(merged.get("take_profit_pct", 0.20)),
        min_hold_days=int(merged.get("min_hold_days", 15)),
        rsi_buy=float(merged.get("rsi_buy", 40.0)),
        near_low60_pct=float(merged.get("near_low60_pct", 0.05)),
        ma60_buy_band=float(merged.get("ma60_buy_band", 0.02)),
        ma20_pullback_band=float(merged.get("ma20_pullback_band", 0.02)),
        ma120_floor=floor,
        weekly_only=bool(merged.get("weekly_only", False)),
        sell_on_ma60_recover=bool(merged.get("sell_on_ma60_recover", True)),
        sell_ma60_band=float(merged.get("sell_ma60_band", 0.02)),
        trend_break_ma60=bool(merged.get("trend_break_ma60", True)),
        max_positions=int(merged.get("max_positions", 3)),
        single_budget=float(merged.get("single_budget", 10_000.0)),
        max_daily_new_positions=int(merged.get("max_daily_new_positions", 1)),
    )


def horizon_enabled(config: dict | None = None) -> bool:
    return load_horizon(config=config).enabled
