"""
sim.precision — monetary/price precision helpers.

REQ-016: keep broker average-cost snapshots (for example 32.818) from
being silently rounded to two decimals.  All helpers accept float/str/Decimal
and quantize via Decimal so binary float noise does not leak into persistence
or reports.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_DOWN, ROUND_UP
from typing import Any

from sim.config import get as cfg_get


_ROUNDING_MODES = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
    "ROUND_DOWN": ROUND_DOWN,
    "ROUND_UP": ROUND_UP,
}


def _decimal_places(path: str, default: int) -> int:
    try:
        return int(cfg_get(path, default))
    except Exception:
        return default


def _rounding_mode():
    name = str(cfg_get("precision.rounding", "ROUND_HALF_UP") or "ROUND_HALF_UP").upper()
    return _ROUNDING_MODES.get(name, ROUND_HALF_UP)


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    # str(value) preserves user-entered decimals such as 32.818 and avoids
    # Decimal(32.818) binary-float expansion.
    return Decimal(str(value))


def quantize_value(value: Any, places: int) -> float:
    q = Decimal("1").scaleb(-int(places))
    return float(_to_decimal(value).quantize(q, rounding=_rounding_mode()))


def quantize_price(value: Any) -> float:
    """Market/trade price precision (default 3 decimals for snapshot fidelity)."""
    return quantize_value(value, _decimal_places("precision.price_decimals", 3))


def quantize_cost(value: Any) -> float:
    """Average cost precision (default 3 decimals; broker costs may include fees)."""
    return quantize_value(value, _decimal_places("precision.cost_decimals", 3))


def quantize_amount(value: Any) -> float:
    """Cash/amount precision (default 2 decimals)."""
    return quantize_value(value, _decimal_places("precision.amount_decimals", 2))


def fmt_value(value: Any, places: int) -> str:
    return f"{quantize_value(value, places):.{int(places)}f}"


def fmt_price(value: Any) -> str:
    return fmt_value(value, _decimal_places("precision.price_decimals", 3))


def fmt_cost(value: Any) -> str:
    return fmt_value(value, _decimal_places("precision.cost_decimals", 3))


def fmt_amount(value: Any) -> str:
    return fmt_value(value, _decimal_places("precision.amount_decimals", 2))
