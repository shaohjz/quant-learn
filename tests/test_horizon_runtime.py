"""horizon_runtime 持有天数与配置加载。"""

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from horizon_runtime import hold_days_from_trades
from quant_core.horizon import HorizonParams, load_horizon


def test_hold_days_from_last_open_lot():
    rows = [
        ("2026-01-05", "BUY"),
        ("2026-01-20", "SELL"),
        ("2026-02-02", "BUY"),
    ]
    assert hold_days_from_trades(rows, date(2026, 2, 12)) == 10


def test_load_horizon_account_overlay():
    cfg = {
        "horizon": {
            "enabled": True,
            "stop_loss_pct": 0.12,
            "accounts": {3: {"style": "trend_pullback", "weekly_only": True, "min_hold_days": 15}},
        }
    }
    a3 = load_horizon(3, config=cfg)
    assert a3.enabled is True
    assert a3.style == "trend_pullback"
    assert a3.weekly_only is True
    assert a3.min_hold_days == 15
    a1 = load_horizon(1, config=cfg)
    assert a1.style == "mean_revert"
    off = load_horizon(1, config={"horizon": {"enabled": False}})
    assert off.enabled is False
    assert isinstance(off, HorizonParams)
