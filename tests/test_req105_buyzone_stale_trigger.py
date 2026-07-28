"""REQ-105 / TASK-20260709: 脏 buy_zone.trigger 必须拦截。"""
from __future__ import annotations

import importlib.util
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sim_executor", ROOT / "scripts" / "sim_executor.py"
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_stale_trigger_blocked_even_if_price_near_live_ma10():
    """天赐材料：trigger=47.66, price=37.51≈live MA10=38 → 必须拦截。"""
    code = "002709"
    mod._MA10_CACHE[code] = (time.time(), 38.0)
    ok, reason = mod._check_buy_zone_ma_deviation(
        code, {"trigger": 47.66, "level": "buy_zone"}, 37.51
    )
    assert ok is False, reason
    assert "过期" in reason or "REQ-105" in reason


def test_fresh_trigger_near_price_allowed():
    code = "600021"
    mod._MA10_CACHE[code] = (time.time(), 14.30)
    ok, reason = mod._check_buy_zone_ma_deviation(
        code, {"trigger": 14.37, "level": "buy_zone"}, 14.21
    )
    assert ok is True, reason


def test_fetch_fail_hard_block_when_price_far_from_trigger():
    """行情失败 + 现价相对 trigger 偏 >15% → fail-closed。"""
    code = "600186"
    mod._MA10_CACHE.pop(code, None)

    fake_bs = types.ModuleType("baostock")
    fake_bs.login = lambda: None
    fake_bs.logout = lambda: None

    def _query(*_a, **_k):
        raise RuntimeError("baostock down")

    fake_bs.query_history_k_data_plus = _query
    prev = sys.modules.get("baostock")
    sys.modules["baostock"] = fake_bs
    try:
        ok, reason = mod._check_buy_zone_ma_deviation(
            code, {"trigger": 11.75, "level": "buy_zone"}, 8.93
        )
    finally:
        if prev is None:
            sys.modules.pop("baostock", None)
        else:
            sys.modules["baostock"] = prev

    assert ok is False, reason
    assert "拦截" in reason or "REQ-105" in reason
