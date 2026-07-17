"""Closed-trade FIFO analytics for realized PnL review (REQ-023).

The live mirror and simulator both persist executed buys/sells into ``sim_trades``.
This module reconstructs closed trades with FIFO lots so reports can review
realized history instead of only current floating PnL.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Callable, Iterable, Any
import sqlite3

from sim.trade_attribution import entry_signal_label, is_non_strategy_entry


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


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except Exception:
        return None


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except Exception:
        if isinstance(row, dict):
            return row.get(key, default)
        return default


def fetch_trade_rows(
    account_id: int,
    as_of: date | None = None,
    *,
    conn_factory: Callable[[], sqlite3.Connection] | None = None,
) -> list[dict]:
    """Fetch normalized trade rows from ``sim_trades``.

    ``as_of`` is inclusive and can be omitted to analyze the whole history.
    The function deliberately uses ``SELECT *`` because older local mirrors may
    have slightly different optional columns (trade_time, broker, context).
    """
    if conn_factory is None:
        from sim.db import get_conn as conn_factory  # lazy import keeps tests easy

    conn = conn_factory()
    try:
        sql = "SELECT * FROM sim_trades WHERE account_id=?"
        params: list[Any] = [account_id]
        if as_of is not None:
            sql += " AND trade_date<=?"
            params.append(as_of.isoformat())
        # Keep ordering compatible with old/minimal test schemas that may not
        # have optional trade_time/created_at columns.
        sql += " ORDER BY trade_date, id"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def build_closed_trades(trades: Iterable[dict]) -> list[dict]:
    """Reconstruct closed trades using FIFO lots.

    One output record corresponds to one SELL transaction (possibly consuming
    multiple buy lots). Fees are allocated proportionally to the matched shares.
    If a SELL cannot be matched to prior buys, the unmatched quantity is ignored
    rather than fabricating a cost basis.
    """
    lots: dict[str, list[dict]] = defaultdict(list)
    closed: list[dict] = []

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
        trade_date = _parse_date(_row_get(row, 'trade_date'))

        if direction == 'BUY':
            buy_reason = _row_get(row, 'signal_reason') or ''
            buy_broker = _row_get(row, 'broker') or ''
            lots[code].append({
                'remaining_qty': qty,
                'price': price,
                'fee_per_share': fee / qty if qty else 0.0,
                'trade_date': trade_date,
                'trade_id': _row_get(row, 'id'),
                'signal_reason': buy_reason,
                'broker': buy_broker,
                'entry_signal': entry_signal_label(buy_reason),
                'is_strategy': not is_non_strategy_entry(buy_reason, buy_broker),
            })
            continue

        remaining = qty
        matched_qty = 0
        cost_total = 0.0
        buy_fee_total = 0.0
        buy_dates: list[date] = []
        source_lots: list[dict] = []
        strategy_qty = 0
        entry_signals: list[str] = []

        while remaining > 0 and lots[code]:
            lot = lots[code][0]
            take = min(_as_int(lot.get('remaining_qty')), remaining)
            if take <= 0:
                lots[code].pop(0)
                continue
            matched_qty += take
            cost_total += take * _as_float(lot.get('price'))
            buy_fee_total += take * _as_float(lot.get('fee_per_share'))
            if lot.get('trade_date'):
                buy_dates.append(lot['trade_date'])
            if lot.get('is_strategy'):
                strategy_qty += take
            entry_signals.append(str(lot.get('entry_signal') or 'unknown'))
            source_lots.append({
                'buy_trade_id': lot.get('trade_id'),
                'qty': take,
                'price': _as_float(lot.get('price')),
                'date': lot.get('trade_date').isoformat() if lot.get('trade_date') else None,
                'entry_signal': lot.get('entry_signal') or 'unknown',
                'is_strategy': bool(lot.get('is_strategy')),
            })
            lot['remaining_qty'] -= take
            remaining -= take
            if lot['remaining_qty'] <= 0:
                lots[code].pop(0)

        if matched_qty <= 0:
            continue

        sell_fee = fee * (matched_qty / qty) if qty else 0.0
        sell_amount = matched_qty * price
        avg_cost = cost_total / matched_qty if matched_qty else 0.0
        pnl = sell_amount - cost_total - buy_fee_total - sell_fee
        invested = cost_total + buy_fee_total
        pnl_pct = pnl / invested * 100.0 if invested > 0 else 0.0
        first_buy_date = min(buy_dates) if buy_dates else None
        holding_days = (trade_date - first_buy_date).days if trade_date and first_buy_date else None
        # Majority-lot rule: treat as strategy only when most matched shares came from strategy buys.
        is_strategy = strategy_qty >= (matched_qty / 2.0) if matched_qty else False
        # Prefer first strategy label; fall back to first lot label.
        entry_signal = next((s for s in entry_signals if s != 'init_snapshot'), entry_signals[0] if entry_signals else 'unknown')

        closed.append({
            'account_id': _as_int(_row_get(row, 'account_id')),
            'sell_trade_id': _row_get(row, 'id'),
            'close_date': trade_date.isoformat() if trade_date else str(_row_get(row, 'trade_date') or ''),
            'stock_code': code,
            'stock_name': _row_get(row, 'stock_name') or code,
            'quantity': matched_qty,
            'avg_cost': avg_cost,
            'sell_price': price,
            'cost_amount': cost_total,
            'sell_amount': sell_amount,
            'buy_fee': buy_fee_total,
            'sell_fee': sell_fee,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'holding_days': holding_days,
            'broker': _row_get(row, 'broker') or 'sim',
            'signal_reason': _row_get(row, 'signal_reason') or '',
            'entry_signal': entry_signal,
            'is_strategy': is_strategy,
            'source_lots': source_lots,
        })

    return closed


def summarize_closed_trades(closed: Iterable[dict]) -> dict:
    """Aggregate closed-trade metrics for review/dashboard display."""
    rows = list(closed)
    total = len(rows)
    wins = [r for r in rows if _as_float(r.get('pnl')) > 0]
    losses = [r for r in rows if _as_float(r.get('pnl')) < 0]
    gross_profit = sum(_as_float(r.get('pnl')) for r in wins)
    gross_loss = abs(sum(_as_float(r.get('pnl')) for r in losses))
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = -gross_loss / len(losses) if losses else 0.0

    by_symbol: dict[str, dict] = {}
    for r in rows:
        code = str(r.get('stock_code') or '')
        item = by_symbol.setdefault(code, {
            'stock_code': code,
            'stock_name': r.get('stock_name') or code,
            'closed_count': 0,
            'win_count': 0,
            'quantity': 0,
            'pnl': 0.0,
            'sell_amount': 0.0,
            'avg_pnl_pct': 0.0,
        })
        item['closed_count'] += 1
        item['win_count'] += 1 if _as_float(r.get('pnl')) > 0 else 0
        item['quantity'] += _as_int(r.get('quantity'))
        item['pnl'] += _as_float(r.get('pnl'))
        item['sell_amount'] += _as_float(r.get('sell_amount'))
        item['avg_pnl_pct'] += _as_float(r.get('pnl_pct'))

    symbol_rows = []
    for item in by_symbol.values():
        if item['closed_count']:
            item['avg_pnl_pct'] = item['avg_pnl_pct'] / item['closed_count']
            item['win_rate'] = item['win_count'] / item['closed_count'] * 100.0
        else:
            item['win_rate'] = 0.0
        symbol_rows.append(item)
    symbol_rows.sort(key=lambda x: abs(x['pnl']), reverse=True)

    max_profit_trade = max(rows, key=lambda r: _as_float(r.get('pnl')), default=None)
    max_loss_trade = min(rows, key=lambda r: _as_float(r.get('pnl')), default=None)
    avg_holding_days_values = [_as_float(r.get('holding_days')) for r in rows if r.get('holding_days') is not None]

    return {
        'closed_count': total,
        'win_count': len(wins),
        'loss_count': len(losses),
        'win_rate': len(wins) / total * 100.0 if total else 0.0,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
        'net_pnl': gross_profit - gross_loss,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'payoff_ratio': (avg_win / abs(avg_loss)) if avg_loss else None,
        'profit_factor': (gross_profit / gross_loss) if gross_loss > 0 else (None if gross_profit == 0 else float('inf')),
        'avg_holding_days': (sum(avg_holding_days_values) / len(avg_holding_days_values)) if avg_holding_days_values else None,
        'max_profit_trade': max_profit_trade,
        'max_loss_trade': max_loss_trade,
        'by_symbol': symbol_rows,
    }


def analyze_closed_trades(
    account_id: int,
    as_of: date | None = None,
    *,
    conn_factory: Callable[[], sqlite3.Connection] | None = None,
    limit: int | None = None,
    strategy_only: bool = True,
) -> dict:
    """Return closed-trade rows and summary for an account.

    ``strategy_only=True`` (default) excludes init-snapshot / live-mirror sync
    lots from the primary win-rate / expectancy summary so dashboard numbers
    reflect automatic strategy edge instead of imported real holdings.
    """
    trades = fetch_trade_rows(account_id, as_of, conn_factory=conn_factory)
    closed = build_closed_trades(trades)
    closed.sort(key=lambda r: (r.get('close_date') or '', _as_int(r.get('sell_trade_id'))), reverse=True)
    strategy_closed = [r for r in closed if r.get('is_strategy')]
    excluded = [r for r in closed if not r.get('is_strategy')]
    primary = strategy_closed if strategy_only else closed
    summary = summarize_closed_trades(primary)
    summary_all = summarize_closed_trades(closed)
    return {
        'account_id': account_id,
        'as_of': as_of.isoformat() if as_of else None,
        'strategy_only': strategy_only,
        'summary': summary,
        'summary_all': summary_all,
        'excluded_non_strategy_count': len(excluded),
        'closed_trades': primary[:limit] if limit else primary,
        'closed_trades_all': closed[:limit] if limit else closed,
        'total_closed_trades': len(primary),
        'total_closed_trades_all': len(closed),
    }
