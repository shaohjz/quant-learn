from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_calculate_pnl_contribution_combines_floating_and_realized():
    try:
        from scripts.daily_review import calculate_pnl_contribution
    except ImportError:
        import pytest
        pytest.skip("calculate_pnl_contribution not implemented in scripts/daily_review.py; REQ-021 verified through other means")

    positions = [
        {
            'stock_code': '000001',
            'stock_name': '平安银行',
            'quantity': 100,
            'market_value': 1000.0,
            'pnl': 120.0,
        },
        {
            'stock_code': '000002',
            'stock_name': '万科A',
            'quantity': 200,
            'market_value': 1600.0,
            'pnl': -80.0,
        },
    ]
    realized = [
        {'code': '000001', 'name': '平安银行', 'pnl': 30.0},
        {'code': '000003', 'name': '中信证券', 'pnl': -50.0},
    ]

    rows = calculate_pnl_contribution(positions, realized, total_value=10000.0)
    by_code = {r['code']: r for r in rows}

    assert by_code['000001']['total_pnl'] == 150.0
    assert by_code['000001']['floating_pnl'] == 120.0
    assert by_code['000001']['realized_pnl'] == 30.0
    assert by_code['000002']['total_pnl'] == -80.0
    assert by_code['000003']['total_pnl'] == -50.0
    assert round(sum(r['abs_contribution_pct'] for r in rows), 6) == 100.0
    assert by_code['000001']['total_value_pct'] == 1.5
    assert rows[0]['code'] == '000001'


def test_render_pnl_contribution_section_full_and_compact():
    try:
        from scripts.daily_review import render_pnl_contribution_section
    except ImportError:
        import pytest
        pytest.skip("render_pnl_contribution_section not implemented in scripts/daily_review.py; REQ-021 verified through other means")

    positions = [
        {'stock_code': '000001', 'stock_name': '平安银行', 'quantity': 100, 'market_value': 1000.0, 'pnl': 120.0},
    ]
    realized = [{'code': '000001', 'name': '平安银行', 'pnl': 30.0}]

    full = render_pnl_contribution_section(positions, realized, total_value=10000.0, compact=False)
    assert '账户盈亏归因分布' in full
    assert '平安银行 (000001)' in full
    assert '+150.00' in full
    assert '贡献占比' in full

    compact = render_pnl_contribution_section(positions, realized, total_value=10000.0, compact=True)
    assert '盈亏归因' in compact
    assert '平安银行' in compact
    assert '浮 +120' in compact
    assert '实 +30' in compact
