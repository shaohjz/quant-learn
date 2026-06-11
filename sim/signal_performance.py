"""Signal-level realized PnL analytics for strategy validation (REQ-030).

This module attributes closed-trade PnL back to the BUY signal that opened the
matched FIFO lot.  It lets the daily review answer questions like whether
``buy_zone`` or ``buy_strong`` entries are actually profitable after execution.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Callable, Iterable
import json
import re
import sqlite3


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except Exception:
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except Exception:
        return default


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except Exception:
        if isinstance(row, dict):
            return row.get(key, default)
        return default


def _parse_detail(raw: Any) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def normalize_signal(raw_reason: Any = '', raw_detail: Any = None) -> str:
    """Return a stable signal label from ``signal_detail``/``signal_reason``.

    Preference order:
    1. structured detail keys (trigger_type/signal/level/rule)
    2. common strategy tags embedded in reason text (buy_zone, buy_strong, ...)
    3. short cleaned reason prefix
    4. ``unknown``
    """
    detail = _parse_detail(raw_detail)
    for key in ('trigger_type', 'signal', 'level', 'rule'):
        val = detail.get(key)
        if val:
            return str(val).strip()

    rules = detail.get('triggered_rules') or []
    if isinstance(rules, list):
        for item in rules:
            if isinstance(item, dict):
                val = item.get('signal') or item.get('level') or item.get('rule') or item.get('indicator')
                if val:
                    return str(val).strip()
            elif item:
                return str(item).strip()

    reason = str(raw_reason or '').strip()
    if not reason:
        return 'unknown'

    # Preserve canonical tags that already exist in the project.
    match = re.search(r'\b(buy_zone|buy_strong|buy_weak|right_confirm|stop_loss|take_profit|ai_buy|qlib_buy|manual)\b', reason, re.I)
    if match:
        return match.group(1).lower()

    cleaned = re.sub(r'^[自动手工\s:：-]+', '', reason).strip()
    cleaned = re.split(r'[|，,；;。\n]', cleaned, maxsplit=1)[0].strip()
    return (cleaned or reason)[:32]


def fetch_trade_rows(
    account_id: int,
    as_of: date | None = None,
    *,
    conn_factory: Callable[[], sqlite3.Connection] | None = None,
) -> list[dict]:
    """Fetch trades for signal performance analysis."""
    if conn_factory is None:
        from sim.db import get_conn as conn_factory

    conn = conn_factory()
    try:
        sql = "SELECT * FROM sim_trades WHERE account_id=?"
        params: list[Any] = [account_id]
        if as_of is not None:
            sql += " AND trade_date<=?"
            params.append(as_of.isoformat())
        sql += " ORDER BY trade_date, id"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def build_signal_segments(trades: Iterable[dict]) -> list[dict]:
    """Build realized PnL segments attributed to opening BUY signals.

    A single SELL may consume multiple BUY lots.  Each consumed lot creates a
    segment whose PnL is calculated from that lot's cost basis and proportional
    sell fees, then attributed to the BUY lot's normalized signal.
    """
    lots: dict[str, list[dict]] = defaultdict(list)
    segments: list[dict] = []

    for row in trades:
        direction = str(_row_get(row, 'direction', '') or '').upper()
        code = str(_row_get(row, 'stock_code', '') or '')
        if not code or direction not in {'BUY', 'SELL'}:
            continue

        qty = _as_int(_row_get(row, 'quantity'))
        price = _as_float(_row_get(row, 'price'))
        if qty <= 0 or price <= 0:
            continue

        fee = _as_float(_row_get(row, 'commission')) + _as_float(_row_get(row, 'tax'))

        if direction == 'BUY':
            signal = normalize_signal(_row_get(row, 'signal_reason'), _row_get(row, 'signal_detail'))
            lots[code].append({
                'remaining_qty': qty,
                'price': price,
                'fee_per_share': fee / qty if qty else 0.0,
                'signal': signal,
                'signal_reason': _row_get(row, 'signal_reason') or '',
                'buy_trade_id': _row_get(row, 'id'),
                'buy_date': _row_get(row, 'trade_date'),
            })
            continue

        remaining = qty
        sell_fee_per_share = fee / qty if qty else 0.0
        while remaining > 0 and lots[code]:
            lot = lots[code][0]
            take = min(_as_int(lot.get('remaining_qty')), remaining)
            if take <= 0:
                lots[code].pop(0)
                continue

            buy_price = _as_float(lot.get('price'))
            buy_fee = take * _as_float(lot.get('fee_per_share'))
            sell_fee = take * sell_fee_per_share
            cost_amount = take * buy_price
            sell_amount = take * price
            pnl = sell_amount - cost_amount - buy_fee - sell_fee
            invested = cost_amount + buy_fee
            pnl_pct = pnl / invested * 100.0 if invested > 0 else 0.0

            segments.append({
                'signal': lot.get('signal') or 'unknown',
                'stock_code': code,
                'stock_name': _row_get(row, 'stock_name') or code,
                'quantity': take,
                'buy_trade_id': lot.get('buy_trade_id'),
                'sell_trade_id': _row_get(row, 'id'),
                'buy_date': lot.get('buy_date'),
                'close_date': _row_get(row, 'trade_date'),
                'buy_price': buy_price,
                'sell_price': price,
                'cost_amount': cost_amount,
                'sell_amount': sell_amount,
                'pnl': pnl,
                'pnl_pct': pnl_pct,
                'signal_reason': lot.get('signal_reason') or '',
                'broker': _row_get(row, 'broker') or 'sim',
            })

            lot['remaining_qty'] -= take
            remaining -= take
            if lot['remaining_qty'] <= 0:
                lots[code].pop(0)

    return segments


def summarize_signal_segments(segments: Iterable[dict]) -> dict:
    """Aggregate signal-attributed realized PnL segments."""
    rows = list(segments)
    by_signal: dict[str, dict] = {}
    for seg in rows:
        signal = str(seg.get('signal') or 'unknown')
        item = by_signal.setdefault(signal, {
            'signal': signal,
            'closed_count': 0,
            'win_count': 0,
            'loss_count': 0,
            'quantity': 0,
            'gross_profit': 0.0,
            'gross_loss': 0.0,
            'net_pnl': 0.0,
            'sell_amount': 0.0,
            'avg_pnl_pct': 0.0,
            'symbols': set(),
        })
        pnl = _as_float(seg.get('pnl'))
        item['closed_count'] += 1
        item['quantity'] += _as_int(seg.get('quantity'))
        item['sell_amount'] += _as_float(seg.get('sell_amount'))
        item['net_pnl'] += pnl
        item['avg_pnl_pct'] += _as_float(seg.get('pnl_pct'))
        if pnl > 0:
            item['win_count'] += 1
            item['gross_profit'] += pnl
        elif pnl < 0:
            item['loss_count'] += 1
            item['gross_loss'] += abs(pnl)
        if seg.get('stock_code'):
            item['symbols'].add(str(seg.get('stock_code')))

    signal_rows = []
    for item in by_signal.values():
        n = item['closed_count']
        item['win_rate'] = item['win_count'] / n * 100.0 if n else 0.0
        item['avg_pnl_pct'] = item['avg_pnl_pct'] / n if n else 0.0
        item['profit_factor'] = (
            item['gross_profit'] / item['gross_loss'] if item['gross_loss'] > 0
            else (None if item['gross_profit'] == 0 else float('inf'))
        )
        item['symbol_count'] = len(item['symbols'])
        item['symbols'] = sorted(item['symbols'])
        signal_rows.append(item)

    signal_rows.sort(key=lambda r: (abs(r['net_pnl']), r['closed_count']), reverse=True)
    total_profit = sum(_as_float(r.get('pnl')) for r in rows if _as_float(r.get('pnl')) > 0)
    total_loss = abs(sum(_as_float(r.get('pnl')) for r in rows if _as_float(r.get('pnl')) < 0))
    return {
        'segment_count': len(rows),
        'signal_count': len(signal_rows),
        'net_pnl': sum(_as_float(r.get('pnl')) for r in rows),
        'gross_profit': total_profit,
        'gross_loss': total_loss,
        'by_signal': signal_rows,
        'segments': rows,
    }


def analyze_signal_performance(
    account_id: int,
    as_of: date | None = None,
    *,
    conn_factory: Callable[[], sqlite3.Connection] | None = None,
    limit: int | None = None,
) -> dict:
    """Return signal-level realized PnL analytics for an account."""
    trades = fetch_trade_rows(account_id, as_of, conn_factory=conn_factory)
    segments = build_signal_segments(trades)
    summary = summarize_signal_segments(segments)
    if limit is not None:
        summary['by_signal'] = summary['by_signal'][:limit]
    return {
        'account_id': account_id,
        'as_of': as_of.isoformat() if as_of else None,
        'summary': summary,
    }
