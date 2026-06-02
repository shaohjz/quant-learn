from __future__ import annotations

import importlib
import os
from datetime import date
from types import SimpleNamespace


def _load_qmt_broker_with_db(tmp_path):
    os.environ["QUANT_DB_PATH"] = str(tmp_path / "sim_live_mirror.db")
    import sim.db as db

    importlib.reload(db)
    db.init_tables()

    import broker.qmt_broker as qmt_broker

    importlib.reload(qmt_broker)
    return db, qmt_broker


def test_qmt_dry_run_submission_is_audited_in_sim_orders(tmp_path):
    db, qmt_broker = _load_qmt_broker_with_db(tmp_path)

    broker = qmt_broker.QMTBroker(
        qmt_path="D:/fake/userdata_mini",
        account_id="90072426",
        local_account_id=1,
        dry_run=True,
    )
    broker.connect()
    result = broker.buy("600519", 100.0, 100, stock_name="贵州茅台", signal_reason="BUG-013 audit")

    assert result.success
    assert result.order_id and result.order_id.startswith("DRY")

    conn = db.get_conn()
    try:
        row = conn.execute(
            """
            SELECT broker, status, stock_code, direction, quantity, broker_order_id, signal_reason
              FROM sim_orders
             WHERE broker_order_id=?
            """,
            (result.order_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["broker"] == "qmt_dry_run"
    assert row["status"] == "DRY_RUN"
    assert row["direction"] == "BUY"
    assert row["stock_code"] == "600519"
    assert row["quantity"] == 100
    assert row["signal_reason"] == "BUG-013 audit"


def test_qmt_trade_callback_writes_existing_sim_trades_columns(tmp_path):
    db, qmt_broker = _load_qmt_broker_with_db(tmp_path)

    broker = qmt_broker.QMTBroker(
        qmt_path="D:/fake/userdata_mini",
        account_id="90072426",
        local_account_id=1,
        dry_run=True,
    )
    order_id = "QMT123456"
    broker._order_meta[order_id] = {
        "side": qmt_broker.OrderSide.BUY,
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "signal_reason": "filled audit",
        "signal_detail": {"source": "unit-test"},
        "trade_date": date(2026, 6, 1),
    }
    broker._record_order_submission(
        order_id=order_id,
        side=qmt_broker.OrderSide.BUY,
        stock_code="600519",
        stock_name="贵州茅台",
        price=100.0,
        quantity=100,
        signal_reason="filled audit",
        status="SUBMITTED",
        broker="qmt",
    )

    trade = SimpleNamespace(
        order_id=order_id,
        stock_code="600519",
        stock_name="贵州茅台",
        traded_price=101.5,
        traded_volume=100,
        order_type=23,
    )
    broker._on_trade_filled(trade)

    conn = db.get_conn()
    try:
        row = conn.execute(
            """
            SELECT trade_date, stock_code, stock_name, direction, price, quantity,
                   broker, broker_order_id, signal_detail
              FROM sim_trades
             WHERE broker_order_id=?
            """,
            (order_id,),
        ).fetchone()
        order = conn.execute(
            "SELECT status, traded FROM sim_orders WHERE broker_order_id=?",
            (order_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["trade_date"] == "2026-06-01"
    assert row["direction"] == "BUY"
    assert row["broker"] == "qmt"
    assert row["broker_order_id"] == order_id
    assert '"source": "unit-test"' in row["signal_detail"]
    fill = conn.execute(
        "SELECT order_id, stock_code, direction, trade_price, trade_volume, broker FROM sim_fills WHERE order_id=?",
        (order_id,),
    ).fetchone()

    assert order["status"] == "ALL_TRADED"
    assert order["traded"] == 100
    assert fill is not None
    assert fill["broker"] == "qmt"
    assert fill["trade_volume"] == 100
    assert fill["trade_price"] == 101.5


def test_qmt_order_status_callback_updates_sim_orders(tmp_path):
    db, qmt_broker = _load_qmt_broker_with_db(tmp_path)

    broker = qmt_broker.QMTBroker(
        qmt_path="D:/fake/userdata_mini",
        account_id="90072426",
        local_account_id=1,
        dry_run=True,
    )
    order_id = "QMT_STATUS_1"
    broker._order_meta[order_id] = {
        "side": qmt_broker.OrderSide.SELL,
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "signal_reason": "status stream",
        "submit_price": 100.0,
        "submit_quantity": 200,
    }

    order = SimpleNamespace(
        order_id=order_id,
        stock_code="600519",
        stock_name="贵州茅台",
        order_type=24,
        price=99.5,
        order_volume=200,
        traded_volume=100,
        order_status="PART_TRADED",
        order_time="2026-06-01 10:01:02",
    )
    broker._on_order_status(order)

    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT broker_order_id, direction, quantity, traded, price, status, signal_reason FROM sim_orders WHERE broker_order_id=?",
            (order_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["direction"] == "SELL"
    assert row["quantity"] == 200
    assert row["traded"] == 100
    assert row["status"] == "PART_TRADED"
    assert row["signal_reason"] == "status stream"
