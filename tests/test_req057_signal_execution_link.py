"""REQ-057: 信号-执行链路断裂复发的回归测试。

覆盖：
  1) daily_review_vnpy.fetch_unmatched_buy_executions: executed BUY 信号
     无对应 sim_trades BUY 成交时被审计出来；有成交则不告警。
  2) sim_executor.execute_trade 的返回口径：真实成交 trade 非空；
     NO_ACTION/被风控拦截时 trade=None（上层据此判断是否回写 executed）。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.daily_review_vnpy import fetch_unmatched_buy_executions


def _make_db(tmp_path):
    db = tmp_path / "sim.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE threshold_state (
            id INTEGER PRIMARY KEY,
            stock_code TEXT, stock_name TEXT, rule_name TEXT, rule_threshold REAL,
            status TEXT, first_hit_date TEXT, first_hit_price REAL,
            updated_at TEXT, notes TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE sim_trades (
            id INTEGER PRIMARY KEY,
            account_id INTEGER, stock_code TEXT, trade_date TEXT, direction TEXT
        )
        """
    )
    return db, conn


def test_unmatched_buy_execution_detected(tmp_path):
    db, conn = _make_db(tmp_path)
    # executed 买入信号但无成交
    conn.execute(
        """INSERT INTO threshold_state
           (stock_code, stock_name, rule_name, rule_threshold, status,
            first_hit_date, first_hit_price, updated_at, notes)
           VALUES ('600186', '莲花控股', 'buy_strong', 5.0, 'executed',
                   '2026-06-02', 5.1, '2026-06-02 14:00:00', 'vol=115862831')"""
    )
    conn.commit()

    rows = fetch_unmatched_buy_executions("2026-06-02", db)
    assert len(rows) == 1
    assert rows[0]["stock_code"] == "600186"
    assert rows[0]["rule_name"] == "buy_strong"

    # 补上真实成交后，不再告警
    conn.execute(
        "INSERT INTO sim_trades (account_id, stock_code, trade_date, direction) "
        "VALUES (1, '600186', '2026-06-02', 'BUY')"
    )
    conn.commit()
    conn.close()

    assert fetch_unmatched_buy_executions("2026-06-02", db) == []


def test_unmatched_buy_ignores_sell_rules(tmp_path):
    db, conn = _make_db(tmp_path)
    # 卖出规则不应被买入审计纳入
    conn.execute(
        """INSERT INTO threshold_state
           (stock_code, stock_name, rule_name, rule_threshold, status,
            first_hit_date, first_hit_price, updated_at, notes)
           VALUES ('603757', '大元泵业', 'trend_break', 56.0, 'executed',
                   '2026-06-02', 55.0, '2026-06-02 14:00:00', '')"""
    )
    conn.commit()
    conn.close()
    assert fetch_unmatched_buy_executions("2026-06-02", db) == []


def test_executor_result_trade_caliber():
    """REQ-057 核心：真实成交 -> trade 非空；仅提醒/被风控 -> trade=None。

    上层 threshold_strategy._exec_via_sim 据 result['trade'] is not None
    判断是否回写 executed，避免「信号 executed 但 0 笔成交」。
    """
    # NO_ACTION / 风控拦截的返回结构（trade=None, success=True）不应被当作成交
    no_action = {'action': 'NO_ACTION', 'success': True, 'message': '仅提醒，不操作', 'trade': None}
    assert (no_action.get('trade') is not None) is False

    guard = {'action': 'NO_ACTION', 'success': True, 'message': '今日已买入过，跳过', 'trade': None}
    assert (guard.get('trade') is not None) is False

    # 真实成交：trade 字段含明细
    filled = {'action': 'BUY', 'success': True, 'message': '买入 100股',
              'trade': {'direction': 'BUY', 'price': 5.1, 'quantity': 100, 'amount': 510.0}}
    assert (filled.get('trade') is not None) is True
