from decimal import Decimal

import sim.precision as precision


def test_cost_precision_defaults_to_three_decimals():
    assert precision.quantize_cost(32.8184) == 32.818
    assert precision.fmt_cost(Decimal("32.818")) == "32.818"


def test_amount_precision_defaults_to_two_decimals():
    assert precision.quantize_amount(Decimal("13127.199")) == 13127.20
    assert precision.fmt_amount(Decimal("13127.2")) == "13127.20"


def test_precision_config_can_override_cost_decimals(monkeypatch):
    def fake_cfg(path, default=None):
        overrides = {
            "precision.cost_decimals": 4,
            "precision.rounding": "ROUND_HALF_UP",
        }
        return overrides.get(path, default)

    monkeypatch.setattr(precision, "cfg_get", fake_cfg)
    assert precision.quantize_cost("32.81845") == 32.8185
    assert precision.fmt_cost("32.81845") == "32.8185"
