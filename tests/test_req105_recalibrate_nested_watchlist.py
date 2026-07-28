"""daily_recalibrate 必须展开嵌套 watchlist（REQ-105 根因）。"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

# daily_recalibrate imports baostock at module level; stub if missing
if "baostock" not in sys.modules:
    sys.modules["baostock"] = types.ModuleType("baostock")

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "daily_recalibrate", ROOT / "scripts" / "daily_recalibrate.py"
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_nested_watchlist_expands_real_codes():
    wl = {
        "user_manual": {
            "002709": {"name": "天赐材料", "enabled": True, "rules": {}},
            "600186": {"name": "莲花控股", "enabled": True, "rules": {}},
        },
        "auto_discovered": {},
    }
    codes = mod.collect_calibration_codes(
        wl, auto_discovered={"300017": {"name": "网宿科技", "enabled": True, "rules": {}}}
    )
    assert "002709" in codes
    assert "600186" in codes
    assert "300017" in codes
    assert codes["300017"]["config_file"] == "auto"
    assert "user_manual" not in codes
    assert "auto_discovered" not in codes


def test_flat_watchlist_still_works():
    wl = {"000725": {"name": "京东方A", "enabled": True, "rules": {}}}
    codes = mod.collect_calibration_codes(wl)
    assert set(codes) == {"000725"}
    assert codes["000725"]["name"] == "京东方A"
