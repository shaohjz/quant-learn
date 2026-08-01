"""策略记分卡：滚动统计口径与漂移告警。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.strategy_scorecard import (
    build_scorecard,
    detect_alarms,
    group_stats,
    render_markdown,
    staleness_alarm,
    window_rows,
)


def _row(day, sig_type="A", fwd_5d=0.01, executable=1, executed=0, **kw):
    base = {
        "signal_date": day,
        "strategy": "swing",
        "signal_type": sig_type,
        "executable": executable,
        "executed": executed,
        "fwd_1d": fwd_5d / 5 if fwd_5d is not None else None,
        "fwd_5d": fwd_5d,
        "fwd_10d": fwd_5d,
        "hit_take_profit_5d": 1 if (fwd_5d or 0) > 0.05 else 0,
        "hit_stop_5d": 1 if (fwd_5d or 0) < -0.05 else 0,
        "fwd_max_gain_5d": max(fwd_5d or 0, 0),
        "fwd_max_draw_5d": min(fwd_5d or 0, 0),
    }
    base.update(kw)
    return base


def _many(n, day_start=1, **kw):
    return [_row(f"2026-06-{day_start + i:02d}", **kw) for i in range(n)]


def test_window_counts_signal_days_not_calendar_days():
    """滚动窗口按有信号的交易日数，节假日不该消耗窗口。"""
    rows = [_row("2026-06-01"), _row("2026-06-10"), _row("2026-06-20")]
    assert len(window_rows(rows, 2)) == 2
    assert {r["signal_date"] for r in window_rows(rows, 2)} == {"2026-06-10", "2026-06-20"}


def test_immature_signals_excluded_from_return_stats():
    """还没填到 5 日的信号不能算进胜率，否则新信号会稀释统计。"""
    rows = [_row("2026-06-01", fwd_5d=0.10), _row("2026-06-02", fwd_5d=None)]
    stats = group_stats(rows)[0]
    assert stats.samples == 2
    assert stats.matured == 1
    assert stats.mean_fwd_5d == 0.10
    assert stats.win_rate == 1.0


def test_negative_expectancy_on_executable_type_is_critical():
    stats = group_stats(_many(25, fwd_5d=-0.02, executable=1))
    alarms = detect_alarms(stats, min_samples=20)
    codes = [a.code for a in alarms]
    assert "executable_negative_expectancy" in codes
    assert next(a for a in alarms if a.code == "executable_negative_expectancy").level == "critical"


def test_small_sample_does_not_trigger_alarm():
    """小样本翻正负是常态，不该天天喊狼。"""
    stats = group_stats(_many(5, fwd_5d=-0.05, executable=1))
    assert detect_alarms(stats, min_samples=20) == []


def test_ignored_signal_outperforming_is_surfaced():
    """C/D/E/F 只观察不买；若它们明显更强，必须提出来进研究队列。"""
    rows = _many(25, sig_type="A", fwd_5d=0.005, executable=1)
    rows += _many(25, sig_type="D", fwd_5d=0.05, executable=0)
    alarms = detect_alarms(group_stats(rows), min_samples=20)
    hit = [a for a in alarms if a.code == "ignored_signal_outperforms"]
    assert len(hit) == 1
    assert "D" in hit[0].message


def test_stop_dominance_warns_that_stop_may_be_too_tight():
    rows = _many(12, fwd_5d=-0.06, executable=1) + _many(12, day_start=13, fwd_5d=0.07, executable=1)
    # 12 笔触止损、12 笔触止盈 → 比例相同，不该告警
    assert not [a for a in detect_alarms(group_stats(rows), min_samples=20) if a.code == "stop_before_target"]

    rows = _many(20, fwd_5d=-0.06, executable=1) + _many(5, day_start=21, fwd_5d=0.07, executable=1)
    alarms = detect_alarms(group_stats(rows), min_samples=20)
    assert [a for a in alarms if a.code == "stop_before_target"]


def test_signals_never_executed_is_critical():
    """信号到执行链路断裂是这个项目反复出现的 P0，记分卡必须能自己发现。"""
    stats = group_stats(_many(25, executable=1, executed=0))
    alarms = detect_alarms(stats, min_samples=20)
    assert "signals_never_executed" in [a.code for a in alarms]


def test_executed_signals_clear_the_link_alarm():
    stats = group_stats(_many(25, executable=1, executed=1))
    assert "signals_never_executed" not in [a.code for a in detect_alarms(stats, min_samples=20)]


def test_empty_ledger_is_flagged():
    alarm = staleness_alarm([], as_of="2026-08-01")
    assert alarm is not None
    assert alarm.code == "ledger_empty"


def test_stale_ledger_is_flagged():
    """闭环最常见的死法是没人发现它停了。"""
    alarm = staleness_alarm([_row("2026-07-01")], as_of="2026-08-01")
    assert alarm is not None
    assert alarm.code == "ledger_stale"
    assert alarm.context["gap_days"] == 31


def test_fresh_ledger_not_flagged():
    assert staleness_alarm([_row("2026-07-30")], as_of="2026-07-31") is None


def test_scorecard_reports_all_windows_and_verdict():
    rows = _many(28, fwd_5d=0.02, executable=1, executed=1)
    card = build_scorecard(rows, as_of="2026-06-28", windows=(20, 60))
    assert set(card["windows"]) == {"20d", "60d"}
    assert card["windows"]["20d"]["signal_days"] == 20
    assert card["windows"]["60d"]["signal_days"] == 28
    assert card["read_only"] is True
    assert "5日平均 +2.00%" in card["verdict"]


def test_alarms_only_from_longest_window():
    """短窗噪声大；告警只用最长窗口，避免结论天天变脸。"""
    rows = _many(25, fwd_5d=-0.02, executable=1, executed=1)
    card = build_scorecard(rows, as_of="2026-06-25", windows=(20, 60))
    negative = [a for a in card["alarms"] if a["code"] == "executable_negative_expectancy"]
    assert len(negative) == 1


def test_verdict_flags_critical_first():
    rows = _many(25, fwd_5d=-0.02, executable=1, executed=0)
    card = build_scorecard(rows, as_of="2026-06-25")
    assert card["verdict"].startswith("异常：")


def test_markdown_renders_without_data():
    card = build_scorecard([], as_of="2026-08-01")
    md = render_markdown(card)
    assert "策略记分卡" in md
    assert "ledger_empty" in md


def test_markdown_contains_group_table():
    card = build_scorecard(_many(25, fwd_5d=0.02, executed=1), as_of="2026-06-25")
    md = render_markdown(card)
    assert "| 策略 | 型 | 可成交 |" in md
    assert "swing" in md
