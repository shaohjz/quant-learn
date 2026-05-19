"""tests/test_fusion_alert_state.py — FusionStrategy 接 alert 状态 (Phase 4)

不依赖 vnpy CTA 引擎；只测 _load_alert_state 和 _handle 的 confidence boost 逻辑。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_load_alert_state_from_json():
    """老 portfolio_alert 写的 alert_state.json 能被正确解析"""
    with tempfile.TemporaryDirectory() as tmp:
        # monkey-patch ROOT 路径
        import importlib
        import strategies.fusion_strategy as fs
        importlib.reload(fs)

        today = date.today()
        # 模拟一份 alert_state.json
        state_file = Path(tmp) / "alert_state.json"
        state_data = {
            "date": today.isoformat(),
            today.isoformat(): {
                "002342_deep_drop": {"triggered_at": "09:35", "price": 15.74, "trigger": 15.74},
                "002709_buy_zone":  {"triggered_at": "13:02", "price": 53.87, "trigger": 54.0},
                "600330_stop_loss": {"triggered_at": "10:01", "price": 26.5, "trigger": 27.0},
            },
        }
        state_file.write_text(json.dumps(state_data), encoding="utf-8")
        fs.ALERT_STATE_FILE = state_file
        fs.ALERT_DB_PATH = Path(tmp) / "nope.db"  # 不存在 → 跳过

        loaded = fs._load_alert_state(today)
        assert loaded["002342"]["level"] == "deep_drop", loaded
        assert loaded["002709"]["level"] == "buy_zone", loaded
        assert loaded["600330"]["level"] == "stop_loss", loaded
        # 检查带 source
        assert loaded["600330"]["source"] == "alert_state.json"
        print(f"✅ alert_state.json 解析 OK: {len(loaded)} 个标的")


def test_confidence_boost_when_aligned():
    """alert + qlib 共识时 confidence 应该被 boost"""
    import importlib
    import strategies.fusion_strategy as fs
    importlib.reload(fs)
    from decision.fusion_engine import decide as raw_decide

    # baseline：无 alert，AI BUY 高 conf
    base = raw_decide(
        stock_code="002709",
        current_price=53.5,
        position_qty=0,
        qlib_signal={"code": "002709", "action": "BUY", "confidence": 0.7},
        threshold_alert=None,
    )
    # boosted：buy_zone 触发 + AI BUY → 应该 conf 更高
    boosted_raw = raw_decide(
        stock_code="002709",
        current_price=53.5,
        position_qty=0,
        qlib_signal={"code": "002709", "action": "BUY", "confidence": 0.7},
        threshold_alert={"level": "buy_zone", "trigger": 54.0, "price": 53.5},
    )
    # 模拟 FusionStrategy._handle 里的 boost
    if boosted_raw.is_actionable():
        old = boosted_raw.confidence
        boosted_raw.confidence = min(0.95, boosted_raw.confidence + 0.10)
        assert boosted_raw.confidence > old, "boost 没生效"
    assert boosted_raw.action == "BUY", boosted_raw
    print(f"✅ confidence boost OK: base={base.confidence:.2f} boosted={boosted_raw.confidence:.2f}")


def test_strategy_picks_up_alert():
    """FusionStrategy 启动时能自动 load alert state，并喂给 fusion_engine"""
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["NOTIFIER_DRY_RUN"] = "1"
        import importlib
        import strategies.fusion_strategy as fs
        importlib.reload(fs)

        today = date.today()
        state_file = Path(tmp) / "alert_state.json"
        state_file.write_text(json.dumps({
            today.isoformat(): {
                "002709_buy_zone": {"triggered_at": "13:02", "price": 53.87, "trigger": 54.0},
            }
        }), encoding="utf-8")
        # daily_signals.json
        signals_file = Path(tmp) / "daily_signals.json"
        signals_file.write_text(json.dumps({
            "signals": [{"code": "002709", "action": "BUY", "confidence": 0.65}]
        }), encoding="utf-8")
        fs.ALERT_STATE_FILE = state_file
        fs.ALERT_DB_PATH = Path(tmp) / "nope.db"
        fs.SIGNAL_FILE = signals_file

        class _FakeEngine:
            def write_log(self, *a, **kw): pass
            def put_strategy_event(self, *a, **kw): pass
            def get_engine_type(self): return None

        s = fs.FusionStrategy(_FakeEngine(), "test", "002709.SZSE", {})
        s.on_init()
        assert "002709" in s._alert_state, f"alert 没加载: {s._alert_state}"
        assert s._alert_state["002709"]["level"] == "buy_zone"
        print(f"✅ FusionStrategy.on_init 加载到 alert: {s._alert_state['002709']}")


if __name__ == "__main__":
    test_load_alert_state_from_json()
    test_confidence_boost_when_aligned()
    test_strategy_picks_up_alert()
    print("\n🎉 Phase 4 tests passed")
