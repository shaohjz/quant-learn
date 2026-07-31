"""账户 #1 buy_zone 与账户 #3 波段 A/B 纯函数测试。"""

from dataclasses import replace
from datetime import date

import pytest

from quant_core.buy_strategies import (
    Account1BuyInput,
    Account1BuyParams,
    ExistingPosition,
    SwingBuyInput,
    SwingBuyParams,
    evaluate_account1_buy_zone,
    evaluate_account3_swing,
)
from quant_core.domain import Direction, SignalIntent

TODAY = date(2026, 7, 31)


def account1_input(**changes) -> Account1BuyInput:
    baseline = Account1BuyInput(
        symbol="000001",
        date=TODAY,
        close=9.90,
        buy_zone=10.00,
        ma10=10.00,
        ma20=9.80,
        volume_ratio=1.10,
        market_change_pct=-0.50,
        expected_rr=1.20,
    )
    return replace(baseline, **changes)


def swing_input(**changes) -> SwingBuyInput:
    baseline = SwingBuyInput(
        symbol="600036",
        date=TODAY,
        close=10.00,
        ma10=11.00,
        ma20=10.00,
        volume_ratio=0.79,
        expected_rr=1.20,
        auxiliary_score=1,
    )
    return replace(baseline, **changes)


class TestAccount1BuyZone:
    def test_baseline_and_exact_boundaries_allow(self):
        result = evaluate_account1_buy_zone(
            account1_input(
                close=10.00,
                market_change_pct=-0.99,
                expected_rr=1.20,
            )
        )

        assert result.allowed is True
        assert result.reason_code == "BUY_ZONE"
        assert result.setup == "buy_zone"
        intent = result.to_signal_intent()
        assert isinstance(intent, SignalIntent)
        assert intent.direction is Direction.LONG
        assert intent.target_price == 10.00
        assert intent.as_of == TODAY

    @pytest.mark.parametrize(
        ("changes", "reason_code"),
        [
            ({"close": 10.01}, "ABOVE_BUY_ZONE"),
            ({"market_change_pct": -1.00}, "WEAK_MARKET"),
            (
                {
                    "position": ExistingPosition(
                        quantity=100,
                        pnl_pct=-3.00,
                    )
                },
                "ADD_TO_LOSER",
            ),
        ],
    )
    def test_baseline_buy_blocks(self, changes, reason_code):
        result = evaluate_account1_buy_zone(account1_input(**changes))

        assert result.allowed is False
        assert result.reason_code == reason_code
        assert result.to_signal_intent() is None

    def test_rr_gate_is_candidate_not_baseline_behavior(self):
        baseline = evaluate_account1_buy_zone(account1_input(expected_rr=0.5))
        candidate = evaluate_account1_buy_zone(
            account1_input(expected_rr=1.19),
            Account1BuyParams(min_expected_rr=1.2),
        )

        assert baseline.allowed is True
        assert candidate.reason_code == "RR_TOO_LOW"

    def test_position_loss_does_not_block_new_position(self):
        result = evaluate_account1_buy_zone(
            account1_input(
                position=ExistingPosition(quantity=0, pnl_pct=-20.0),
            )
        )

        assert result.allowed is True

    def test_parameters_are_configurable(self):
        params = Account1BuyParams(
            weak_market_change_pct=-2.0,
            block_add_to_loser_pct=-5.0,
            min_expected_rr=1.0,
        )
        result = evaluate_account1_buy_zone(
            account1_input(
                market_change_pct=-1.5,
                expected_rr=1.0,
                position=ExistingPosition(quantity=100, pnl_pct=-4.0),
            ),
            params,
        )

        assert result.allowed is True

    def test_candidate_can_block_falling_knife_and_require_trend(self):
        too_far = evaluate_account1_buy_zone(
            account1_input(close=9.0, buy_zone=10.0, ma10=10.0),
            Account1BuyParams(max_below_ma10_pct=0.05),
        )
        weak_trend = evaluate_account1_buy_zone(
            account1_input(ma10=9.8, ma20=10.0, close=9.7, buy_zone=9.8),
            Account1BuyParams(require_ma10_above_ma20=True),
        )

        assert too_far.reason_code == "TOO_FAR_BELOW_MA10"
        assert weak_trend.reason_code == "TREND_NOT_CONFIRMED"

    def test_close_must_also_be_at_or_below_ma10(self):
        result = evaluate_account1_buy_zone(account1_input(close=10.0, buy_zone=10.2, ma10=9.9))

        assert result.reason_code == "ABOVE_BUY_ZONE"


class TestAccount3Swing:
    @pytest.mark.parametrize("close", [9.85, 10.15])
    def test_a_ma20_band_boundaries_are_inclusive(self, close):
        result = evaluate_account3_swing(swing_input(close=close))

        assert result.allowed is True
        assert result.setup == "A"
        assert result.score == 5

    @pytest.mark.parametrize("close", [9.90, 10.10])
    def test_b_ma10_band_boundaries_are_inclusive(self, close):
        result = evaluate_account3_swing(swing_input(close=close, ma10=10.00, ma20=12.00, auxiliary_score=2))

        assert result.allowed is True
        assert result.setup == "B"
        assert result.score == 5

    def test_volume_ratio_boundary_is_exclusive(self):
        result = evaluate_account3_swing(swing_input(volume_ratio=0.80))

        assert result.allowed is False
        assert result.reason_code == "VOLUME_TOO_HIGH"

    def test_overlapping_a_b_scores_are_added_and_a_has_priority(self):
        result = evaluate_account3_swing(swing_input(ma10=10.00, ma20=10.00))

        assert result.allowed is True
        assert result.setup == "A"
        assert result.matched_setups == ("A", "B")
        assert result.score == 8

    @pytest.mark.parametrize(
        ("data", "params", "reason_code"),
        [
            (swing_input(close=10.20), SwingBuyParams(), "NO_AB_SETUP"),
            (swing_input(expected_rr=1.19), SwingBuyParams(), "RR_TOO_LOW"),
            (
                swing_input(auxiliary_score=0),
                SwingBuyParams(),
                "SCORE_TOO_LOW",
            ),
        ],
    )
    def test_swing_block_conditions(self, data, params, reason_code):
        result = evaluate_account3_swing(data, params)

        assert result.allowed is False
        assert result.reason_code == reason_code
        assert result.to_signal_intent() is None

    def test_swing_parameters_are_configurable(self):
        params = SwingBuyParams(
            a_ma20_tolerance=0.02,
            max_volume_ratio=0.9,
            min_expected_rr=1.0,
        )
        result = evaluate_account3_swing(
            swing_input(close=10.19, volume_ratio=0.89, expected_rr=1.0),
            params,
        )

        assert result.allowed is True
        assert result.setup == "A"


def test_functions_do_not_perform_io(monkeypatch):
    def fail_io(*args, **kwargs):
        raise AssertionError("纯函数不应访问 IO")

    monkeypatch.setattr("builtins.open", fail_io)

    account1 = evaluate_account1_buy_zone(account1_input())
    swing = evaluate_account3_swing(swing_input())

    assert account1.allowed is True
    assert swing.allowed is True


@pytest.mark.parametrize(
    "data",
    [
        account1_input(close=0),
        account1_input(expected_rr=float("nan")),
    ],
)
def test_invalid_account1_numeric_input_fails_fast(data):
    with pytest.raises(ValueError):
        evaluate_account1_buy_zone(data)
