"""tests/test_order_replay.py -- apps.order_replay 单元测试"""
from __future__ import annotations
from datetime import datetime, timedelta
from unittest.mock import MagicMock
import pytest

pytestmark = pytest.mark.qmt
pytest.importorskip("vnpy", reason="vnpy tests require the optional Windows trading environment")

from vnpy.trader.constant import Status, Direction, Offset, Exchange, OrderType
from vnpy.trader.object import OrderData, TradeData

NOW = datetime(2026, 5, 31, 10, 0, 0)


def _make_order(orderid="001", symbol="600330", exchange=Exchange.SSE,
                direction=Direction.LONG, offset=Offset.OPEN,
                price=32.0, volume=100.0, traded=0.0,
                status=Status.SUBMITTING, dt=None, gateway="sim"):
    return OrderData(
        gateway_name=gateway, symbol=symbol, exchange=exchange,
        orderid=orderid, type=OrderType.LIMIT,
        direction=direction, offset=offset,
        price=price, volume=volume, traded=traded,
        status=status, datetime=dt or NOW,
    )


def _make_trade(orderid="001", tradeid="T001", symbol="600330",
                 exchange=Exchange.SSE, direction=Direction.LONG, offset=Offset.OPEN,
                 price=32.0, volume=100.0, dt=None, gateway="sim"):
    return TradeData(
        gateway_name=gateway, symbol=symbol, exchange=exchange,
        orderid=orderid, tradeid=tradeid,
        direction=direction, offset=offset,
        price=price, volume=volume, datetime=dt or NOW,
    )


def _make_oms_engine(orders, trades):
    oms = MagicMock()
    order_dict = {o.vt_orderid: o for o in orders}
    trade_dict = {t.tradeid: t for t in trades}
    # get_order 返回订单（用于检查状态）
    oms.get_order.side_effect = lambda vid: order_dict.get(vid)
    # get_all_orders 返回所有订单
    oms.get_all_orders.return_value = list(order_dict.values())
    # get_all_trades 返回所有成交
    oms.get_all_trades.return_value = list(trade_dict.values())
    return oms

class TestBuildReplay:
    def test_empty_oms(self):
        from apps.order_replay import build_replay
        oms = _make_oms_engine([], [])
        events = build_replay(oms)
        assert events == []

    def test_single_order_submitted(self):
        from apps.order_replay import build_replay, ReplayEventType
        order = _make_order(status=Status.SUBMITTING, traded=0)
        oms = _make_oms_engine([order], [])
        events = build_replay(oms)
        assert len(events) >= 1
        submitted = [e for e in events if e.event_type == ReplayEventType.ORDER_SUBMITTED]
        assert len(submitted) == 1

    def test_order_fully_traded_in_one_shot(self):
        from apps.order_replay import build_replay, ReplayEventType
        order = _make_order(status=Status.ALLTRADED, traded=100)
        trade = _make_trade(tradeid="T01", volume=100, price=31.5)
        oms = _make_oms_engine([order], [trade])
        events = build_replay(oms)
        types = [e.event_type for e in events]
        assert ReplayEventType.ORDER_SUBMITTED in types
        assert ReplayEventType.ORDER_FULLY_TRADED in types

    def test_order_partial_then_fully_traded(self):
        from apps.order_replay import build_replay, ReplayEventType
        order = _make_order(status=Status.ALLTRADED, traded=100)
        t1 = _make_trade(tradeid="T01", volume=60, price=31.0, dt=NOW + timedelta(seconds=10))
        t2 = _make_trade(tradeid="T02", volume=40, price=31.2, dt=NOW + timedelta(seconds=30))
        oms = _make_oms_engine([order], [t1, t2])
        events = build_replay(oms)
        part = [e for e in events if e.event_type == ReplayEventType.ORDER_PART_TRADED]
        full = [e for e in events if e.event_type == ReplayEventType.ORDER_FULLY_TRADED]
        assert len(part) == 1
        assert len(full) == 1
        assert part[0].datetime < full[0].datetime

    def test_cancelled_order(self):
        from apps.order_replay import build_replay, ReplayEventType
        order = _make_order(status=Status.CANCELLED, traded=30)
        oms = _make_oms_engine([order], [])
        events = build_replay(oms)
        cancel = [e for e in events if e.event_type == ReplayEventType.ORDER_CANCELLED]
        assert len(cancel) == 1

    def test_rejected_order(self):
        from apps.order_replay import build_replay, ReplayEventType
        order = _make_order(status=Status.REJECTED)
        oms = _make_oms_engine([order], [])
        events = build_replay(oms)
        rej = [e for e in events if e.event_type == ReplayEventType.ORDER_REJECTED]
        assert len(rej) == 1

    def test_filter_by_symbol(self):
        from apps.order_replay import build_replay
        o1 = _make_order(orderid="O1", symbol="600330", exchange=Exchange.SSE)
        o2 = _make_order(orderid="O2", symbol="000001", exchange=Exchange.SZSE)
        oms = _make_oms_engine([o1, o2], [])
        events = build_replay(oms, symbol="600330")
        ids = {e.vt_orderid for e in events}
        assert "sim.O1" in ids
        assert "sim.O2" not in ids

    def test_filter_by_vt_orderid(self):
        from apps.order_replay import build_replay
        o1 = _make_order(orderid="target-001")
        o2 = _make_order(orderid="other-002")
        oms = _make_oms_engine([o1, o2], [])
        events = build_replay(oms, vt_orderid="target-001")
        assert len(events) >= 1
        assert all("target-001" in e.vt_orderid for e in events)

    def test_events_sorted_by_datetime(self):
        from apps.order_replay import build_replay
        o1 = _make_order(orderid="O1", dt=NOW + timedelta(minutes=5))
        o2 = _make_order(orderid="O2", dt=NOW)
        oms = _make_oms_engine([o1, o2], [])
        events = build_replay(oms)
        dts = [e.datetime for e in events if e.datetime]
        assert dts == sorted(dts)

class TestBuildOrderSummaries:
    def test_single_order_summary(self):
        from apps.order_replay import build_order_summaries
        order = _make_order(status=Status.ALLTRADED, traded=100)
        trade = _make_trade(tradeid="T01", volume=100, price=31.5)
        oms = _make_oms_engine([order], [trade])
        summaries = build_order_summaries(oms)
        assert len(summaries) == 1
        s = summaries[0]
        assert s.fully_traded_at is not None
        assert len(s.trades) == 1

    def test_cancelled_summary(self):
        from apps.order_replay import build_order_summaries
        order = _make_order(status=Status.CANCELLED, traded=30)
        oms = _make_oms_engine([order], [])
        summaries = build_order_summaries(oms)
        assert summaries[0].cancelled_at is not None


class TestFormatReplayText:
    def test_empty_input(self):
        from apps.order_replay import format_replay_text
        assert "无订单" in format_replay_text([])

    def test_format_contains_symbol(self):
        from apps.order_replay import build_replay, format_replay_text
        order = _make_order(symbol="600330", status=Status.ALLTRADED, traded=100)
        trade = _make_trade(volume=100, price=31.5)
        oms = _make_oms_engine([order], [trade])
        events = build_replay(oms)
        text = format_replay_text(events)
        assert "600330" in text

    def test_format_contains_trade_info(self):
        from apps.order_replay import build_replay, format_replay_text
        order = _make_order(status=Status.ALLTRADED, traded=100)
        trade = _make_trade(volume=100, price=31.5, tradeid="T99")
        oms = _make_oms_engine([order], [trade])
        events = build_replay(oms)
        text = format_replay_text(events)
        assert "T99" in text


class TestIntegration:
    def test_print_replay_runs(self):
        from apps.order_replay import print_replay
        order = _make_order(status=Status.ALLTRADED, traded=100)
        trade = _make_trade(volume=100, price=31.5)
        oms = _make_oms_engine([order], [trade])
        text = print_replay(oms)
        assert text is not None
        assert len(text) > 0

    def test_export_markdown_creates_file(self, tmp_path):
        from apps.order_replay import export_replay_markdown
        order = _make_order(status=Status.ALLTRADED, traded=100)
        trade = _make_trade(volume=100, price=31.5)
        oms = _make_oms_engine([order], [trade])
        fp = str(tmp_path / "replay_test.md")
        md = export_replay_markdown(oms, filepath=fp)
        assert "订单成交回放" in md
        from pathlib import Path
        assert Path(fp).exists()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
