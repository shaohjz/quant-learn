"""REQ-099/101: confirmed 止损必须 SELL_ALL，避免半仓残留 100 股卡死。"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sim_executor", ROOT / "scripts" / "sim_executor.py"
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_confirmed_volume_stop_is_sell_all():
    with patch.object(mod, "_get_today_vol_ratio", return_value=2.0), patch.object(
        mod, "_is_late_session", return_value=False
    ):
        sev, action, reason = mod._check_stop_loss_severity(
            "300146",
            {"trigger": 10.15, "level": "stop_loss"},
            9.84,
            {"trailing_stop_price": 10.15},
        )
    assert sev == "confirmed"
    assert action == "SELL_ALL", reason
    assert "清仓" in reason


def test_late_session_confirmed_is_sell_all():
    with patch.object(mod, "_get_today_vol_ratio", return_value=0.8), patch.object(
        mod, "_is_late_session", return_value=True
    ):
        sev, action, reason = mod._check_stop_loss_severity(
            "300017",
            {"trigger": 13.32, "level": "stop_loss"},
            12.89,
            {},
        )
    assert sev == "confirmed"
    assert action == "SELL_ALL", reason


def test_break_over_1pct_upgrades_to_sell_all():
    with patch.object(mod, "_get_today_vol_ratio", return_value=0.5), patch.object(
        mod, "_is_late_session", return_value=False
    ):
        sev, action, reason = mod._check_stop_loss_severity(
            "000725",
            {"trigger": 5.62, "level": "stop_loss"},
            5.56,  # ~1.07% below stop
            {},
        )
    assert sev == "confirmed"
    assert action == "SELL_ALL", reason
