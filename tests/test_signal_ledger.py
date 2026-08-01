"""信号结果台账：记账幂等性与前瞻收益口径。"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.signal_ledger import (
    STATUS_COMPLETE,
    STATUS_PARTIAL,
    SignalRecord,
    backfill,
    compute_forward_returns,
    ensure_tables,
    fetch_outcomes,
    record_signals,
)


def _conn():
    conn = sqlite3.connect(":memory:")
    ensure_tables(conn)
    return conn


def _rec(**kw):
    base = dict(
        signal_date="2026-07-20",
        account_id=3,
        stock_code="sh600036",
        signal_type="A",
        strategy="swing",
        ref_price=10.0,
    )
    base.update(kw)
    return SignalRecord(**base)


def _bars(closes, highs=None, lows=None, start_day=21):
    out = []
    for i, close in enumerate(closes):
        out.append(
            {
                "date": f"2026-07-{start_day + i:02d}",
                "close": close,
                "high": highs[i] if highs else close,
                "low": lows[i] if lows else close,
            }
        )
    return out


def test_record_is_idempotent_on_same_signal():
    conn = _conn()
    assert record_signals(conn, [_rec()])["inserted"] == 1
    stats = record_signals(conn, [_rec()])
    assert stats == {"inserted": 0, "updated": 1}
    assert len(fetch_outcomes(conn)) == 1


def test_executed_flag_can_upgrade_but_never_downgrade():
    """盘中提醒未成交、收盘补漏成交 → executed 要能 0→1；反向不行。"""
    conn = _conn()
    record_signals(conn, [_rec(executed=False)])
    record_signals(conn, [_rec(executed=True)])
    assert fetch_outcomes(conn)[0]["executed"] == 1

    record_signals(conn, [_rec(executed=False)])
    assert fetch_outcomes(conn)[0]["executed"] == 1


def test_non_executable_signals_are_recorded():
    """C/D/E/F 只观察不买，但必须进台账，否则无法做反事实评估。"""
    conn = _conn()
    record_signals(
        conn,
        [
            _rec(signal_type="A", executable=True),
            _rec(signal_type="D", executable=False),
        ],
    )
    rows = {r["signal_type"]: r for r in fetch_outcomes(conn)}
    assert rows["D"]["executable"] == 0
    assert len(rows) == 2


def test_forward_returns_use_close_for_horizons():
    m = compute_forward_returns(10.0, _bars([10.5, 11.0, 9.0, 9.5, 12.0]), 0.05, 0.08)
    assert m["fwd_1d"] == 0.05
    assert m["fwd_3d"] == -0.10
    assert m["fwd_5d"] == 0.20
    assert "fwd_10d" not in m  # 只有 5 根bar，10日不该编造
    assert m["bars_filled"] == 5


def test_stop_and_target_hits_use_intraday_range():
    """止损/止盈按 high/low 判定：只看收盘会系统性低估止损命中率。"""
    # 第一根 bar 收盘持平但盘中最低触及 -6%
    m = compute_forward_returns(
        10.0,
        _bars([10.0, 10.0], highs=[10.1, 10.1], lows=[9.4, 9.9]),
        stop_loss_pct=0.05,
        take_profit_pct=0.08,
    )
    assert m["hit_stop_5d"] == 1
    assert m["hit_take_profit_5d"] == 0


def test_stop_wins_when_both_touched_in_same_bar():
    """同一 bar 内止损止盈都触及时保守算止损先到，不虚报策略表现。"""
    m = compute_forward_returns(
        10.0,
        _bars([10.0], highs=[11.0], lows=[9.0]),
        stop_loss_pct=0.05,
        take_profit_pct=0.08,
    )
    assert m["hit_stop_5d"] == 1
    assert m["hit_take_profit_5d"] == 0


def test_backfill_only_uses_bars_after_signal_date():
    """信号日当天及之前的 bar 不能算进前瞻收益，否则等于偷看未来。"""
    conn = _conn()
    record_signals(conn, [_rec(signal_date="2026-07-22", ref_price=10.0)])

    bars = [
        {"date": "2026-07-21", "close": 5.0, "high": 5.0, "low": 5.0},
        {"date": "2026-07-22", "close": 10.0, "high": 10.0, "low": 10.0},
        {"date": "2026-07-23", "close": 11.0, "high": 11.0, "low": 11.0},
    ]
    stats = backfill(conn, lambda code: bars, 0.05, 0.08, as_of="2026-07-23")
    assert stats["updated"] == 1

    row = fetch_outcomes(conn)[0]
    assert row["fwd_1d"] == 0.10  # 用 07-23 而不是 07-21
    assert row["outcome_status"] == STATUS_PARTIAL


def test_backfill_marks_complete_after_ten_bars():
    conn = _conn()
    record_signals(conn, [_rec(ref_price=10.0)])
    bars = _bars([10.0 + i * 0.1 for i in range(12)])
    backfill(conn, lambda code: bars, 0.05, 0.08, as_of="2026-08-05")

    row = fetch_outcomes(conn)[0]
    assert row["outcome_status"] == STATUS_COMPLETE
    assert row["bars_filled"] == 10
    assert row["fwd_10d"] is not None


def test_completed_signals_are_not_refetched():
    conn = _conn()
    record_signals(conn, [_rec(ref_price=10.0)])
    bars = _bars([10.0 + i * 0.1 for i in range(12)])

    calls: list[str] = []

    def fetcher(code):
        calls.append(code)
        return bars

    backfill(conn, fetcher, 0.05, 0.08, as_of="2026-08-05")
    backfill(conn, fetcher, 0.05, 0.08, as_of="2026-08-06")
    assert len(calls) == 1  # 第二次没有 pending，不该再打行情接口


def test_backfill_survives_missing_quotes():
    conn = _conn()
    record_signals(conn, [_rec()])
    stats = backfill(conn, lambda code: None, 0.05, 0.08, as_of="2026-07-25")
    assert stats["no_data"] == 1
    assert stats["updated"] == 0


def test_one_quote_call_per_code_even_with_many_signals():
    conn = _conn()
    record_signals(
        conn,
        [
            _rec(signal_date="2026-07-20", signal_type="A"),
            _rec(signal_date="2026-07-21", signal_type="B"),
            _rec(signal_date="2026-07-22", signal_type="C"),
        ],
    )
    calls: list[str] = []

    def fetcher(code):
        calls.append(code)
        return _bars([10.0] * 12)

    backfill(conn, fetcher, 0.05, 0.08, as_of="2026-08-05")
    assert calls == ["sh600036"]
