"""策略复盘闭环测试。

重点覆盖三件容易出事的地方：
  1. 空库 / 缺文件时不能抛异常 —— 开发机上的 DB 就是空的，链路必须能验证
  2. 小样本统计量必须诚实 —— 置信区间算错会直接误导改参决策
  3. 静默改参必须被抓到 —— 这是整个闭环的守门员
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review import diagnostics  # noqa: E402
from review import ledger as ledger_mod
from review.funnel import build_swing_funnel  # noqa: E402
from review.metrics import (  # noqa: E402
    analyze_account,
    breakeven_win_rate,
    evidence_level,
    expectancy_stats,
    nav_stats,
    samples_needed_for_edge,
    wilson_interval,
)
from review.spec import StrategySpec, load_specs, read_module_constants  # noqa: E402

# ─────────────────────────── spec ───────────────────────────


def test_module_constants_are_read_statically(tmp_path):
    """只认模块级字面量，函数体和条件分支里的一律跳过。"""
    mod = tmp_path / "m.py"
    mod.write_text(
        "TOP = 50\n"
        "RATE = 0.05\n"
        "TYPES = {'A', 'B'}\n"
        "BIG = 1e8\n"
        "def f():\n"
        "    INSIDE = 99\n"
        "    return INSIDE\n"
        "if True:\n"
        "    BRANCHED = 1\n"
        "COMPUTED = TOP * 2\n",
        encoding="utf-8",
    )
    consts = read_module_constants(mod)
    assert consts["TOP"] == 50
    assert consts["RATE"] == 0.05
    assert consts["TYPES"] == {"A", "B"}
    assert consts["BIG"] == 1e8
    assert "INSIDE" not in consts
    assert "BRANCHED" not in consts
    assert "COMPUTED" not in consts


def test_read_module_constants_survives_bad_input(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n", encoding="utf-8")
    assert read_module_constants(bad) == {}
    assert read_module_constants(tmp_path / "missing.py") == {}


def test_live_specs_extract_all_params():
    """真实代码里的参数必须全部抽得到，抽不到说明常量被改名了。"""
    specs = load_specs()
    assert {s.strategy_id for s in specs} == {"swing", "learn"}
    for spec in specs:
        assert not spec.missing(), f"{spec.strategy_id} 抽不到: {[p.key for p in spec.missing()]}"


def test_swing_spec_matches_source_of_truth():
    """抽出来的值必须等于参数真源的生效值。

    这里刻意不写死 0.05 / 3 这类具体数字 —— 参数本来就会随假设验证而变，
    钉死它们只会让测试变成改参数的阻力。DEFAULTS 与迁移前行为一致由
    tests/test_swing_params.py 负责钉。
    """
    params = pytest.importorskip("quant_core.swing_params").load_swing_params()
    spec = next(s for s in load_specs() if s.strategy_id == "swing")
    assert spec.value("stop_loss_pct") == params.stop_loss_pct
    assert spec.value("take_profit_pct") == params.take_profit_pct
    assert spec.value("max_positions") == params.max_positions
    assert spec.value("single_budget") == params.single_budget
    assert set(spec.value("entry_types")) == set(params.executable_types)


def test_swing_spec_prefers_configurable_source_over_script_constant():
    """quant_core/swing_params.py 是生效值，脚本常量只用来对账。"""
    spec = next(s for s in load_specs() if s.strategy_id == "swing")
    stop = spec.get("stop_loss_pct")
    assert stop.refs[0].ref.kind == "params"
    assert {r.ref.kind for r in stop.refs} == {"params", "module"}


def test_partial_migration_detected_even_when_values_agree():
    """值一样也要报：一旦 YAML 调参，只读真源的脚本会变，其余照旧用旧值。"""
    from review.spec import Param, ParamRef, ResolvedRef

    p = Param(
        key="stop_loss_pct", label="止损", group="exit",
        refs=[
            ResolvedRef(ParamRef("params", "swing_params", "execution.stop_loss_pct"), 0.05, True),
            ResolvedRef(ParamRef("module", "scripts/swing_daily_report.py", "STOP_LOSS_PCT"), 0.05, True),
        ],
    )
    spec = StrategySpec(strategy_id="t", account_id=3, name="测试仓", headline="h", params=[p])
    assert not p.conflict  # 值一致，不是冲突

    found = [f for f in diagnostics.check_spec_health(spec) if f.rule_id == "partial_migration"]
    assert len(found) == 1
    assert found[0].severity == "P0"


def test_no_partial_migration_when_only_one_source():
    from review.spec import Param, ParamRef, ResolvedRef

    p = Param(key="x", label="x", group="exit",
              refs=[ResolvedRef(ParamRef("params", "swing_params", "execution.x"), 1, True)])
    spec = StrategySpec(strategy_id="t", account_id=3, name="t", headline="h", params=[p])
    assert not [f for f in diagnostics.check_spec_health(spec) if f.rule_id == "partial_migration"]


def test_spec_hash_changes_with_params(tmp_path):
    """spec_hash 是漂移检测的基准，参数一变它必须变。"""
    a = load_specs()[0]
    before = a.spec_hash()
    a.get("max_positions").refs[0].value = 99
    assert a.spec_hash() != before


def test_conflict_detected_when_two_sources_disagree():
    from review.spec import Param, ParamRef, ResolvedRef

    ref_a = ResolvedRef(ParamRef("module", "a.py", "X"), 0.05, True)
    ref_b = ResolvedRef(ParamRef("module", "b.py", "X"), 0.04, True)
    p = Param(key="stop", label="止损", group="exit", refs=[ref_a, ref_b])
    assert p.conflict

    ref_b.value = 0.05
    assert not p.conflict


def test_display_handles_percent_unit_conventions():
    """config 里 -0.08 表示 -8%，-3.0 也表示 -3%，两种约定都要渲染对。"""
    from review.spec import Param, ParamRef, ResolvedRef

    def mk(value, unit):
        return Param(key="k", label="l", group="exit", unit=unit,
                     refs=[ResolvedRef(ParamRef("config", "c.yaml", "k"), value, True)])

    assert mk(0.05, "frac").display() == "5%"
    assert mk(-0.08, "frac").display() == "-8%"
    assert mk(-3.0, "%").display() == "-3%"
    assert mk(10_000.0, "元").display() == "1 万"
    assert mk(1e8, "元").display() == "1 亿"
    assert mk(True, "").display() == "开"


# ───────────────────────── metrics ─────────────────────────


def test_wilson_interval_is_wide_for_small_samples():
    lo, hi = wilson_interval(6, 10)
    assert 0.30 < lo < 0.33
    assert 0.82 < hi < 0.85
    # 样本变大区间必须收窄，否则「证据等级」失去意义
    lo2, hi2 = wilson_interval(60, 100)
    assert (hi2 - lo2) < (hi - lo)


def test_wilson_interval_edge_cases():
    assert wilson_interval(0, 0) == (0.0, 1.0)
    lo, hi = wilson_interval(0, 10)
    assert lo == 0.0 and hi < 1.0
    lo, hi = wilson_interval(10, 10)
    assert lo > 0.0 and hi == 1.0


def test_breakeven_win_rate():
    assert breakeven_win_rate(1.6) == pytest.approx(0.3846, abs=1e-4)
    assert breakeven_win_rate(1.0) == pytest.approx(0.5)
    assert breakeven_win_rate(0) is None
    assert breakeven_win_rate(None) is None


def test_samples_needed_for_edge():
    assert samples_needed_for_edge(0.6) == pytest.approx(91, abs=3)
    assert samples_needed_for_edge(0.5) is None  # 没有优势就无从证明
    assert samples_needed_for_edge(0.4) is None


def test_evidence_level_tiers():
    assert evidence_level(0)["level"] == "none"
    assert evidence_level(3)["level"] == "anecdote"
    assert evidence_level(10)["level"] == "weak"
    assert evidence_level(25)["level"] == "usable"
    assert evidence_level(100)["level"] == "solid"


def test_expectancy_significance():
    noisy = expectancy_stats([2.1, -1.5, 3.0, -0.8, 1.2])
    assert noisy.n == 5
    assert not noisy.significant  # 小样本高方差，不该判显著

    consistent = expectancy_stats([1.0] * 30)
    assert consistent.significant

    assert expectancy_stats([]).n == 0
    assert expectancy_stats([1.5]).mean_pct == 1.5


def test_nav_stats_computes_drawdown_from_values():
    rows = [
        {"trade_date": "2026-07-01", "total_value": 100.0, "daily_return": 0.0},
        {"trade_date": "2026-07-02", "total_value": 120.0, "daily_return": 20.0},
        {"trade_date": "2026-07-03", "total_value": 90.0, "daily_return": -25.0},
        {"trade_date": "2026-07-04", "total_value": 96.0, "daily_return": -1.0},
    ]
    st = nav_stats(rows)
    assert st.days == 4
    assert st.max_drawdown_pct == pytest.approx(25.0)
    assert st.current_drawdown_pct == pytest.approx(20.0)
    assert st.losing_streak == 2
    assert nav_stats([]).days == 0


# ────────────────── 端到端：造一个有样本的库 ──────────────────


def _make_db(path: Path, trades: list[tuple], navs: list[tuple] = ()) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE sim_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, trade_date DATE,
            stock_code TEXT, stock_name TEXT, direction TEXT, price REAL, quantity INTEGER,
            amount REAL, commission REAL, tax REAL, signal_reason TEXT, broker TEXT,
            signal_detail TEXT, trade_time TEXT
        );
        CREATE TABLE sim_daily_nav (
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, trade_date TEXT,
            total_value REAL, cash REAL, market_value REAL, daily_return REAL,
            cumulative_return REAL, max_drawdown REAL
        );
        """
    )
    for t in trades:
        conn.execute(
            "INSERT INTO sim_trades (account_id, trade_date, stock_code, stock_name, direction,"
            " price, quantity, amount, commission, tax, signal_reason, broker)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,'sim')",
            t,
        )
    for n in navs:
        conn.execute(
            "INSERT INTO sim_daily_nav (account_id, trade_date, total_value, cash, market_value,"
            " daily_return, cumulative_return) VALUES (?,?,?,?,?,?,?)",
            n,
        )
    conn.commit()
    conn.close()


@pytest.fixture
def sample_db(tmp_path):
    """两笔完整往返：一笔 buy_zone 赚钱，一笔 buy_zone 止损亏钱。"""
    db = tmp_path / "sim.db"
    _make_db(
        db,
        trades=[
            (1, "2026-07-01", "600000", "甲", "BUY", 10.0, 1000, 10000.0, 5.0, 0.0, "buy_zone|试探建仓"),
            (1, "2026-07-05", "600000", "甲", "SELL", 11.0, 1000, 11000.0, 5.0, 5.5, "take_profit|止盈"),
            (1, "2026-07-06", "600001", "乙", "BUY", 20.0, 500, 10000.0, 5.0, 0.0, "buy_zone|试探建仓"),
            (1, "2026-07-09", "600001", "乙", "SELL", 18.0, 500, 9000.0, 5.0, 4.5, "stop_loss|自动止损"),
        ],
        navs=[
            (1, "2026-07-01", 100000.0, 90000.0, 10000.0, 0.0, 0.0),
            (1, "2026-07-05", 101000.0, 101000.0, 0.0, 1.0, 1.0),
            (1, "2026-07-09", 99900.0, 99900.0, 0.0, -1.1, -0.1),
        ],
    )
    return db


def test_analyze_account_on_real_samples(sample_db):
    perf = analyze_account(sample_db, 1, "#1 学习仓")
    assert perf.closed_count == 2
    assert perf.win_count == 1
    assert perf.win_rate_pct == pytest.approx(50.0)
    assert perf.nav.days == 3
    assert perf.evidence["level"] == "anecdote"  # 2 笔只能算轶事
    # 两笔都由 buy_zone 开仓，应归到同一组
    assert [r["signal"] for r in perf.by_signal] == ["buy_zone"]
    assert perf.by_signal[0]["n"] == 2


def test_analyze_account_never_raises_on_missing_or_empty_db(tmp_path):
    assert analyze_account(tmp_path / "nope.db", 1, "x").closed_count == 0

    empty = tmp_path / "empty.db"
    sqlite3.connect(str(empty)).close()
    perf = analyze_account(empty, 1, "x")
    assert perf.closed_count == 0
    assert perf.nav.days == 0


# ──────────────────────── diagnostics ────────────────────────


def _spec_with(**values) -> StrategySpec:
    from review.spec import Param, ParamRef, ResolvedRef

    params = [
        Param(key=k, label=k, group="sizing",
              refs=[ResolvedRef(ParamRef("config", "c.yaml", k), v, True)])
        for k, v in values.items()
    ]
    return StrategySpec(strategy_id="t", account_id=9, name="测试仓", headline="h", params=params)


def test_capital_cap_contradiction_fires_on_arithmetic():
    spec = _spec_with(max_positions=3, single_budget=10_000.0, initial_cash=50_000.0)
    found = diagnostics.check_capital_structure(spec)
    assert len(found) == 1
    f = found[0]
    assert f.severity == "P0"
    assert f.layer == "execution"  # 算术矛盾不需要样本，当天可改
    assert f.data["cap_pct"] == pytest.approx(60.0)


def test_capital_cap_silent_when_budget_covers_account():
    spec = _spec_with(max_positions=5, single_budget=20_000.0, initial_cash=100_000.0)
    assert diagnostics.check_capital_structure(spec) == []


def test_capital_cap_skipped_when_params_missing():
    assert diagnostics.check_capital_structure(_spec_with(max_positions=3)) == []


def test_edge_check_requires_minimum_samples():
    """样本不足时不许下「胜率不够」的结论。"""
    from review.metrics import AccountPerformance

    p = AccountPerformance(account_id=1, name="x")
    p.closed_count = 5
    p.win_rate_pct = 20.0
    p.payoff_ratio = 1.6
    p.breakeven_win_rate_pct = 38.5
    p.edge_gap_pct = -18.5
    assert diagnostics.check_edge(p) == []  # 5 笔，不下结论

    p.closed_count = 30
    p.win_rate_ci = (0.1, 0.35)
    p.evidence = evidence_level(30)
    found = diagnostics.check_edge(p)
    assert len(found) == 1
    assert found[0].layer == "parameter"  # 参数层，不许当天改


def test_rule_error_is_contained():
    """单条规则炸了不能拖垮整份复盘。"""
    class Boom:
        def conflicts(self):
            raise RuntimeError("boom")

    out = diagnostics._safe(diagnostics.check_spec_health, Boom())
    assert len(out) == 1
    assert out[0].rule_id == "rule_error"


# ─────────────────────────── funnel ───────────────────────────


def _write_funnel_day(root: Path, day: str, pool: dict, daily: dict | None) -> None:
    (root / "output" / "swing_pool").mkdir(parents=True, exist_ok=True)
    (root / "output" / "swing_pool" / f"{day}.json").write_text(
        json.dumps({"date": day, **pool}, ensure_ascii=False), encoding="utf-8"
    )
    if daily is not None:
        (root / "output" / "swing_daily").mkdir(parents=True, exist_ok=True)
        (root / "output" / "swing_daily" / f"{day}.json").write_text(
            json.dumps({"date": day, **daily}, ensure_ascii=False), encoding="utf-8"
        )


def test_funnel_detects_position_cap_blocking(tmp_path):
    for day in ("2026-07-01", "2026-07-02"):
        _write_funnel_day(
            tmp_path, day,
            {"universe_scanned": 800, "candidates": 400, "above_min_score": 200, "top": 50},
            {"advice": [{"hint": "x"}, {"hint": "y"}], "fills": [],
             "positions": [1, 2, 3], "cash": 23000.0, "total": 50000.0},
        )
    fu = build_swing_funnel(root=tmp_path, lookback=10, max_positions=3,
                            single_budget=10_000.0, initial_cash=50_000.0)
    assert fu.blocked_days == 2
    assert fu.zero_fill_streak == 2
    assert fu.capital_cap_pct == pytest.approx(60.0)
    assert fu.idle_cash_pct == pytest.approx(46.0)


def test_raising_position_cap_does_not_erase_history(tmp_path):
    """放宽仓位上限后，「当时出了买点没成交」这个事实必须还在报告里。"""
    for day in ("2026-07-01", "2026-07-02", "2026-07-03"):
        _write_funnel_day(
            tmp_path, day,
            {"universe_scanned": 800, "candidates": 400, "above_min_score": 200, "top": 50},
            {"advice": [{"hint": "x"}], "fills": [], "positions": [1, 2, 3],
             "cash": 23000.0, "total": 50000.0},
        )

    before = build_swing_funnel(root=tmp_path, lookback=10, max_positions=3)
    assert before.blocked_days == 3
    assert before.advice_not_filled_days == 3

    after = build_swing_funnel(root=tmp_path, lookback=10, max_positions=5)
    assert after.blocked_days == 0           # 按新上限不再算满仓拦截
    assert after.advice_not_filled_days == 3  # 但历史事实不变

    spec = _spec_with(max_positions=5, single_budget=10_000.0, initial_cash=50_000.0)
    rules = {f.rule_id for f in diagnostics.check_funnel(after, spec)}
    assert "advice_not_filled" in rules
    assert "position_cap_blocking" not in rules


def test_funnel_does_not_confuse_missing_field_with_fallback(tmp_path):
    """旧版产物没有 above_min_score 字段，不能当成「池子走兜底」误报。"""
    _write_funnel_day(tmp_path, "2026-07-01",
                      {"universe_scanned": 800, "candidates": 400, "top": 20}, None)
    _write_funnel_day(tmp_path, "2026-07-02",
                      {"universe_scanned": 800, "candidates": 400, "above_min_score": 0, "top": 20}, None)

    fu = build_swing_funnel(root=tmp_path, lookback=10)
    legacy, real = fu.days[0], fu.days[1]
    assert legacy.legacy_schema and not legacy.pool_fallback
    assert real.pool_fallback and not real.legacy_schema


def test_funnel_handles_missing_directory(tmp_path):
    fu = build_swing_funnel(root=tmp_path, lookback=5)
    assert fu.days == []
    assert fu.instrumentation_gaps


# ─────────────────────────── ledger ───────────────────────────


def test_unlogged_param_change_is_caught(tmp_path):
    led = ledger_mod.Ledger(tmp_path)
    spec = _spec_with(max_positions=3, single_budget=10_000.0)

    led.record_snapshot([spec], "2026-07-30")

    spec.get("max_positions").refs[0].value = 5
    state = led.build_state([spec], "2026-07-31")

    assert len(state.drifts) == 1
    assert state.unexplained_drifts()
    findings = ledger_mod.check_ledger(state, "2026-07-31")
    assert any(f.rule_id == "unlogged_param_change" and f.severity == "P0" for f in findings)


def test_logged_param_change_is_accepted(tmp_path):
    led = ledger_mod.Ledger(tmp_path)
    spec = _spec_with(max_positions=3)
    led.record_snapshot([spec], "2026-07-30")

    led.open_hypothesis(title="放宽仓位", layer="parameter", today="2026-07-31",
                        param="t.max_positions", before=3, after=5, expect="成交回升")

    spec.get("max_positions").refs[0].value = 5
    state = led.build_state([spec], "2026-07-31")

    assert len(state.drifts) == 1
    assert state.drifts[0].matched_hypothesis == "H-001"
    assert not state.unexplained_drifts()
    assert not [f for f in ledger_mod.check_ledger(state, "2026-07-31")
                if f.rule_id == "unlogged_param_change"]


def test_rerunning_same_day_does_not_swallow_drift(tmp_path):
    """一天跑多次不能把漂移吃掉 —— 基准始终是上一个有记录的日子。"""
    led = ledger_mod.Ledger(tmp_path)
    spec = _spec_with(max_positions=3)
    led.record_snapshot([spec], "2026-07-30")

    spec.get("max_positions").refs[0].value = 5
    first = led.build_state([spec], "2026-07-31")
    second = led.build_state([spec], "2026-07-31")

    assert len(first.drifts) == 1
    assert len(second.drifts) == 1


def test_hypothesis_lifecycle(tmp_path):
    led = ledger_mod.Ledger(tmp_path)
    h = led.open_hypothesis(title="试试", layer="parameter", today="2026-07-01",
                            param="t.x", expect="更好", horizon_days=21)
    assert h.id == "H-001"
    assert h.review_after == "2026-07-22"
    assert not h.is_due("2026-07-10")
    assert h.is_due("2026-07-22")

    state = ledger_mod.LedgerState(hypotheses=led.load_hypotheses())
    assert any(f.rule_id == "hypothesis_due" for f in ledger_mod.check_ledger(state, "2026-07-25"))

    led.close_hypothesis("H-001", ledger_mod.STATUS_REJECTED, "没效果", "2026-07-25")
    reloaded = led.load_hypotheses()[0]
    assert reloaded.status == ledger_mod.STATUS_REJECTED
    assert reloaded.outcome == "没效果"
    # 已结案的不再提醒
    state2 = ledger_mod.LedgerState(hypotheses=led.load_hypotheses())
    assert not [f for f in ledger_mod.check_ledger(state2, "2026-08-01") if f.rule_id == "hypothesis_due"]


def test_ledger_survives_corrupt_files(tmp_path):
    (tmp_path).mkdir(parents=True, exist_ok=True)
    (tmp_path / "hypotheses.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "spec_snapshots.json").write_text("[[[", encoding="utf-8")
    led = ledger_mod.Ledger(tmp_path)
    assert led.load_hypotheses() == []
    assert led.load_snapshots() == []


# ──────────────────────── 主入口端到端 ────────────────────────


def test_cli_end_to_end_on_empty_db(tmp_path, monkeypatch):
    """开发机场景：空库、无漏斗数据，也必须出报告。"""
    import scripts.strategy_review as sr

    db = tmp_path / "empty.db"
    sqlite3.connect(str(db)).close()
    out = tmp_path / "out"

    rc = sr.main([
        "--date", "2026-07-31", "--db", str(db), "--no-push", "--quiet",
        "--ledger-dir", str(tmp_path / "led"), "--out-dir", str(out),
    ])
    assert rc == 0

    md = (out / "2026-07-31.md").read_text(encoding="utf-8")
    payload = json.loads((out / "2026-07-31.json").read_text(encoding="utf-8"))

    assert "策略复盘 2026-07-31" in md
    assert "当前跑的是什么策略" in md
    assert payload["summary"]["headline"]
    assert len(payload["specs"]) == 2


def test_cli_reports_findings_with_layers(tmp_path):
    import scripts.strategy_review as sr

    db = tmp_path / "e.db"
    sqlite3.connect(str(db)).close()
    out = tmp_path / "out"
    sr.main(["--date", "2026-07-31", "--db", str(db), "--no-push", "--quiet",
             "--ledger-dir", str(tmp_path / "led"), "--out-dir", str(out)])

    payload = json.loads((out / "2026-07-31.json").read_text(encoding="utf-8"))

    # 只校验结构，不校验「今天恰好有哪几条发现」—— 后者会随参数修复而变
    assert {f["layer"] for f in payload["findings"]} <= {"execution", "signal", "parameter"}
    assert {f["severity"] for f in payload["findings"]} <= {"P0", "P1", "P2"}
    for f in payload["findings"]:
        assert f["title"] and f["evidence"], f"发现必须带证据: {f['rule_id']}"
        assert f["horizon"], f"发现必须标注可动手时机: {f['rule_id']}"
    assert payload["summary"]["by_layer"].keys() >= {"execution", "signal", "parameter"}


def test_cli_open_and_close_hypothesis(tmp_path, capsys):
    import scripts.strategy_review as sr

    led_dir = tmp_path / "led"
    rc = sr.main(["--date", "2026-07-31", "--ledger-dir", str(led_dir), "--open-hypothesis",
                  "--param", "swing.max_positions", "--expect", "成交回升"])
    assert rc == 0
    assert "H-001" in capsys.readouterr().out

    rc = sr.main(["--date", "2026-08-25", "--ledger-dir", str(led_dir),
                  "--close-hypothesis", "H-001", "--status", "confirmed", "--outcome", "有效"])
    assert rc == 0
    assert json.loads((led_dir / "hypotheses.json").read_text(encoding="utf-8"))[0]["status"] == "confirmed"


def test_cli_rejects_hypothesis_without_expectation(tmp_path):
    """写不出预期的改动不值得做，这条是硬性的。"""
    import scripts.strategy_review as sr

    rc = sr.main(["--date", "2026-07-31", "--ledger-dir", str(tmp_path / "led"),
                  "--open-hypothesis", "--param", "x"])
    assert rc == 2


def test_cli_write_spec_regenerates_doc(tmp_path, monkeypatch):
    import scripts.strategy_review as sr

    fake_docs = tmp_path / "docs"
    fake_docs.mkdir()
    monkeypatch.setattr(sr, "ROOT", tmp_path)
    (tmp_path / "output").mkdir(exist_ok=True)

    db = tmp_path / "e.db"
    sqlite3.connect(str(db)).close()
    sr.main(["--date", "2026-07-31", "--db", str(db), "--no-push", "--quiet", "--write-spec",
             "--ledger-dir", str(tmp_path / "led"), "--out-dir", str(tmp_path / "out")])

    doc = (fake_docs / "STRATEGY_SPEC.md").read_text(encoding="utf-8")
    assert "当前交易策略说明书" in doc
    assert "spec_hash" in doc
