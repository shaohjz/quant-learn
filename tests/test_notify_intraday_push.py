"""盘中企微开关：默认关，只留收盘简报。"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def test_config_default_mutes_intraday():
    from sim.config import load_config, notify_intraday_push_enabled

    load_config.cache_clear()
    assert notify_intraday_push_enabled() is False
    assert (load_config().get("notify") or {}).get("intraday_push") is False


def test_prod_clock_pulse_gets_no_push(monkeypatch):
    import prod_clock as pc

    monkeypatch.setattr(pc, "mute_intraday_wecom", lambda: True)
    monkeypatch.setattr(pc, "trading_day", lambda _dt: True)
    monkeypatch.setattr(pc, "already_done", lambda *_a: True)  # 不掺 once 任务

    dt = datetime(2026, 9, 17, 9, 35, tzinfo=ZoneInfo("Asia/Shanghai"))
    jobs = pc.plan(dt)
    pulse = next(j for j in jobs if j["id"] == "pulse")
    step = pulse["steps"][0]
    assert any(str(p).endswith("quant_pulse.py") for p in step)
    assert "--no-push" in step


def test_prod_clock_close_still_pushes(monkeypatch):
    import prod_clock as pc

    monkeypatch.setattr(pc, "mute_intraday_wecom", lambda: True)
    monkeypatch.setattr(pc, "trading_day", lambda _dt: True)
    monkeypatch.setattr(pc, "already_done", lambda _day, jid: jid != "close")

    dt = datetime(2026, 9, 17, 16, 22, tzinfo=ZoneInfo("Asia/Shanghai"))
    jobs = pc.plan(dt)
    close = next(j for j in jobs if j["id"] == "close")
    step = close["steps"][0]
    assert any("daily_close_report.py" in str(p) for p in step)
    assert "--no-push" not in step


def test_apply_wecom_policy_skips_unknown_scripts(monkeypatch):
    import prod_clock as pc

    monkeypatch.setattr(pc, "mute_intraday_wecom", lambda: True)
    step = ["python", "-u", "/x/scripts/scanner_with_fallback.py"]
    assert pc.apply_wecom_policy(step) == step
