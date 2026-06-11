"""
scripts/daily_review.py — 双账户日复盘 (rewrite 2026-05-22)

核心改进：
  1. 支持双账户：学习账户(id=1, live_mirror) + 真实账户(id=2, real_portfolio)分开复盘
  2. 显示 BUY/SELL 方向、价格、金额、手续费、信号理由
  3. 计算实现盈亏 (FIFO 平仓)
  4. 浮动盈亏从 sim_positions
  5. nav 历史从 sim_daily_nav，自动写入当日
  6. 推送精简版到企微 (markdown)
  7. 完整版本地保存 + 可选写 iwiki
"""
from __future__ import annotations
import os
import sys
import sqlite3
import logging
import requests
from datetime import datetime, date, timedelta, time as dtime
from pathlib import Path
from collections import defaultdict
from math import sqrt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QUANT_DB_PATH', str(ROOT / 'data' / 'sim_live_mirror.db'))

from sim.config import load_config
from sim.market_sentiment import fetch_market_sentiment, render_market_sentiment_section
from sim.asset_allocation import render_allocation_markdown, summarize_allocation

logger = logging.getLogger('daily-review')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

DB = Path(os.environ['QUANT_DB_PATH'])

ACCOUNTS = [
    {'id': 1, 'name': '学习账户', 'icon': '🤖', 'auto': True},
    {'id': 2, 'name': '真实账户', 'icon': '💼', 'auto': False},
]


# =====================================
# 1. 数据查询
# =====================================
def get_conn():
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    return c


def fetch_account(account_id: int):
    c = get_conn()
    r = c.execute('SELECT * FROM sim_account WHERE id=?', (account_id,)).fetchone()
    c.close()
    return dict(r) if r else None


def fetch_positions(account_id: int):
    c = get_conn()
    rows = c.execute(
        'SELECT * FROM sim_positions WHERE account_id=? ORDER BY market_value DESC',
        (account_id,)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def fetch_trades(account_id: int, target_date: date):
    c = get_conn()
    rows = c.execute(
        'SELECT * FROM sim_trades WHERE account_id=? AND trade_date=? ORDER BY id',
        (account_id, target_date.isoformat())
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def fetch_recent_entry_trades(account_id: int, limit: int = 300):
    """Fetch recent trades used to infer current holding strategy buckets (REQ-031)."""
    c = get_conn()
    rows = c.execute(
        'SELECT * FROM sim_trades WHERE account_id=? ORDER BY COALESCE(created_at, trade_date) DESC, id DESC LIMIT ?',
        (account_id, limit)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def fetch_nav_history(account_id: int, target_date: date, n: int = 7):
    c = get_conn()
    rows = c.execute(
        '''SELECT * FROM sim_daily_nav 
           WHERE account_id=? AND trade_date <= ? 
           ORDER BY trade_date DESC LIMIT ?''',
        (account_id, target_date.isoformat(), n)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def fetch_previous_nav(account_id: int, target_date: date):
    """Return latest NAV row before target_date, or None."""
    c = get_conn()
    r = c.execute(
        '''SELECT * FROM sim_daily_nav
           WHERE account_id=? AND trade_date < ?
           ORDER BY trade_date DESC LIMIT 1''',
        (account_id, target_date.isoformat())
    ).fetchone()
    c.close()
    return dict(r) if r else None


def detect_account_basis_changes(account: dict, positions: list, target_date: date, config_initial: float | None = None) -> list[dict]:
    """Detect basis changes that make cross-day returns unsafe (REQ-035)."""
    if not account:
        return []

    warnings: list[dict] = []
    account_id = int(account.get('id') or account.get('account_id') or 1)
    current_market_value = sum(float(p.get('market_value') or 0) for p in positions)
    current_cash = float(account.get('cash') or 0)
    current_total = current_cash + current_market_value
    db_initial = float(account.get('initial_cash') or 0)

    try:
        from sim.db import detect_cash_discrepancy
        disc = detect_cash_discrepancy(account_id)
    except Exception:
        disc = None
    if disc:
        warnings.append({
            'kind': 'initial_cash_mismatch',
            'severity': disc.get('severity', 'warn'),
            'pause_return': True,
            'message': (
                f"config 初始资金 ¥{disc['config_initial_cash']:,.0f} vs "
                f"DB 初始资金 ¥{disc['db_initial_cash']:,.0f} "
                f"（差 ¥{disc['diff']:+,.0f} / {disc['diff_pct']*100:+.1f}%）"
            ),
        })

    try:
        from sim.config import get_account_config
        cfg_name = get_account_config(account_id).get('account_name')
    except Exception:
        cfg_name = None
    db_name = account.get('account_name')
    if cfg_name and db_name and cfg_name != db_name:
        warnings.append({
            'kind': 'account_mapping_mismatch',
            'severity': 'error',
            'pause_return': True,
            'message': f"账户映射疑似变化：config={cfg_name}，DB={db_name}",
        })

    prev = fetch_previous_nav(account_id, target_date)
    if prev:
        prev_total = float(prev.get('total_value') or 0)
        prev_cash = float(prev.get('cash') or 0)
        total_jump = abs(current_total - prev_total) / prev_total if prev_total else 0
        cash_jump = abs(current_cash - prev_cash) / max(abs(prev_cash), 1.0)
        reasons = []
        if total_jump >= 0.20:
            reasons.append(f"总资产从 ¥{prev_total:,.0f} 到 ¥{current_total:,.0f}（{(current_total/prev_total-1)*100:+.1f}%）")
        if cash_jump >= 0.50 and abs(current_cash - prev_cash) >= 1000:
            reasons.append(f"现金从 ¥{prev_cash:,.0f} 到 ¥{current_cash:,.0f}（{current_cash-prev_cash:+,.0f}）")
        if reasons:
            warnings.append({
                'kind': 'snapshot_discontinuity',
                'severity': 'error' if total_jump >= 0.20 else 'warn',
                'pause_return': True,
                'message': f"相对上一净值日 {prev.get('trade_date')} 出现口径跳变：" + '；'.join(reasons),
            })

    if config_initial is not None and db_initial and abs(float(config_initial) - db_initial) / db_initial >= 0.20:
        if not any(w['kind'] == 'initial_cash_mismatch' for w in warnings):
            warnings.append({
                'kind': 'initial_cash_mismatch',
                'severity': 'error',
                'pause_return': True,
                'message': f"初始资金基准变化：config ¥{float(config_initial):,.0f} vs DB ¥{db_initial:,.0f}",
            })

    return warnings


def format_basis_change_warnings(warnings: list[dict]) -> str:
    if not warnings:
        return ''
    lines = ["### ⚠️ 账户资金口径变更提示", ""]
    for w in warnings:
        icon = '🚨' if w.get('severity') == 'error' else '⚠️'
        lines.append(f"- {icon} {w.get('message', '')}")
    if any(w.get('pause_return') for w in warnings):
        lines.append('')
        lines.append('> 已暂停本账户跨日收益率对比：上述变化可能是本金重置、镜像库切换或账户映射变化，不应误判为真实盈亏。')
    return '\n'.join(lines)


def _load_review_alert_thresholds() -> dict:
    """Load configurable thresholds for REQ-020 review anomaly alerts.

    Values in config.yaml/config.local.yaml may be given either as decimals
    (-0.10) or percentages (-10).  Defaults are intentionally conservative so
    the daily review highlights real exceptions without becoming noisy.
    """
    cfg = load_config()
    review_cfg = (cfg.get('review') or {}).get('alerts') or {}
    risk_cfg = cfg.get('risk') or {}

    def pct_value(key: str, default: float) -> float:
        raw = review_cfg.get(key, default)
        try:
            val = float(raw)
        except Exception:
            val = default
        return val / 100.0 if abs(val) > 1 else val

    stop_loss = review_cfg.get('position_loss_pct', risk_cfg.get('stop_loss_pct', -0.10))
    try:
        stop_loss = float(stop_loss)
    except Exception:
        stop_loss = -0.10
    if abs(stop_loss) > 1:
        stop_loss = stop_loss / 100.0

    return {
        'position_loss_pct': stop_loss,
        'watch_loss_pct': pct_value('watch_loss_pct', -0.05),
        'daily_return_drop_pct': pct_value('daily_return_drop_pct', -0.03),
        'drawdown_pct': pct_value('drawdown_pct', -0.10),
        'realized_loss_pct_of_assets': abs(pct_value('realized_loss_pct_of_assets', 0.01)),
        'large_trade_pct_of_assets': abs(pct_value('large_trade_pct_of_assets', 0.20)),
        'large_position_pct_of_assets': abs(pct_value('large_position_pct_of_assets', 0.35)),
        'max_trade_count': int(review_cfg.get('max_trade_count', 5) or 5),
    }


def detect_trade_anomaly_alerts(
    account: dict | None,
    positions: list[dict],
    trades: list[dict],
    realized: list[dict],
    nav: dict | None,
    target_date: date | None = None,
    thresholds: dict | None = None,
) -> list[dict]:
    """Detect review-time anomalies for one account (REQ-020).

    The detector is pure/data-driven so it can be tested without QMT or network:
    - floating loss crossing warning/stop-loss thresholds;
    - large single-position concentration;
    - daily NAV drop / drawdown;
    - large realized losses;
    - unusual trade count or trade amount versus assets.
    """
    thresholds = {**_load_review_alert_thresholds(), **(thresholds or {})}
    alerts: list[dict] = []

    account = account or {}
    total_value = float((nav or {}).get('total_value') or 0)
    if total_value <= 0:
        cash = float(account.get('cash') or 0)
        market_value = sum(float(p.get('market_value') or 0) for p in positions)
        total_value = cash + market_value

    for p in positions:
        code = p.get('stock_code') or p.get('code') or ''
        name = p.get('stock_name') or p.get('name') or code or '未知标的'
        pnl_pct = float(p.get('pnl_pct') or 0) / 100.0
        pnl = float(p.get('pnl') or 0)
        market_value = float(p.get('market_value') or 0)
        if pnl_pct <= thresholds['position_loss_pct']:
            alerts.append({
                'severity': 'critical',
                'kind': 'position_stop_loss',
                'message': f"{name}({code}) 浮亏 {pnl_pct * 100:+.2f}% / {pnl:+,.0f}，已跌破警戒线 {thresholds['position_loss_pct'] * 100:.1f}%",
            })
        elif pnl_pct <= thresholds['watch_loss_pct']:
            alerts.append({
                'severity': 'warn',
                'kind': 'position_watch_loss',
                'message': f"{name}({code}) 浮亏 {pnl_pct * 100:+.2f}% / {pnl:+,.0f}，接近止损区间",
            })
        if total_value > 0 and market_value / total_value >= thresholds['large_position_pct_of_assets']:
            alerts.append({
                'severity': 'warn',
                'kind': 'position_concentration',
                'message': f"{name}({code}) 单票市值占总资产 {market_value / total_value * 100:.1f}%（{_money(market_value)}），仓位较集中",
            })

    if nav:
        daily_return = nav.get('daily_return')
        if daily_return is not None and float(daily_return) / 100.0 <= thresholds['daily_return_drop_pct']:
            alerts.append({
                'severity': 'critical',
                'kind': 'daily_nav_drop',
                'message': f"账户当日收益 {float(daily_return):+.2f}%，跌破 {thresholds['daily_return_drop_pct'] * 100:.1f}% 日内警戒线",
            })
        max_drawdown = nav.get('max_drawdown')
        if max_drawdown is not None and float(max_drawdown) / 100.0 <= thresholds['drawdown_pct']:
            alerts.append({
                'severity': 'warn',
                'kind': 'drawdown',
                'message': f"账户最大回撤 {float(max_drawdown):+.2f}%，超过 {thresholds['drawdown_pct'] * 100:.1f}% 回撤警戒线",
            })

    realized_pnl = sum(float(r.get('pnl') or 0) for r in realized)
    if total_value > 0 and realized_pnl < 0 and abs(realized_pnl) / total_value >= thresholds['realized_loss_pct_of_assets']:
        alerts.append({
            'severity': 'warn',
            'kind': 'realized_loss',
            'message': f"当日实现亏损 {realized_pnl:+,.0f}，占总资产 {abs(realized_pnl) / total_value * 100:.2f}%",
        })

    trade_count = len(trades)
    if trade_count > thresholds['max_trade_count']:
        alerts.append({
            'severity': 'warn',
            'kind': 'trade_count_spike',
            'message': f"当日交易 {trade_count} 笔，超过常规阈值 {thresholds['max_trade_count']} 笔，建议复核是否过度交易",
        })

    trade_amount = sum(float(t.get('amount') or (float(t.get('price') or 0) * int(t.get('quantity') or 0))) for t in trades)
    if total_value > 0 and trade_amount / total_value >= thresholds['large_trade_pct_of_assets']:
        buys = sum(1 for t in trades if t.get('direction') == 'BUY')
        sells = trade_count - buys
        alerts.append({
            'severity': 'warn',
            'kind': 'large_turnover',
            'message': f"当日成交额 {_money(trade_amount)}，约占总资产 {trade_amount / total_value * 100:.1f}%（买 {buys} / 卖 {sells}）",
        })

    return alerts


def format_review_alerts(alerts: list[dict], compact: bool = False, limit: int | None = None) -> str:
    """Render REQ-020 anomaly alerts as Markdown."""
    if not alerts:
        return ''
    limit = limit or (3 if compact else 20)
    shown = alerts[:limit]
    title = "⚠️ 异动/警示" if compact else "### ⚠️ 异动/警示"
    lines = [title]
    for alert in shown:
        icon = '🚨' if alert.get('severity') == 'critical' else '⚠️'
        lines.append(f"- {icon} {alert.get('message', '')}")
    if len(alerts) > len(shown):
        lines.append(f"- … 另有 {len(alerts) - len(shown)} 条，见完整复盘")
    return '\n'.join(lines)


# =====================================
# 1.0 持仓技术面破位分析（REQ-025）
# =====================================
def _load_technical_break_thresholds() -> dict:
    """Load thresholds for position technical-break analysis.

    Config path (optional): review.technical_break.*.  Defaults are deliberately
    data-only and conservative; the analysis is advisory and never places orders.
    """
    cfg = load_config()
    raw = ((cfg.get('review') or {}).get('technical_break') or {})

    def pct_value(key: str, default: float) -> float:
        val = raw.get(key, default)
        try:
            val = float(val)
        except Exception:
            val = default
        return val / 100.0 if abs(val) > 1 else val

    def int_list(key: str, default: list[int]) -> list[int]:
        val = raw.get(key, default)
        if isinstance(val, str):
            val = [x.strip() for x in val.split(',') if x.strip()]
        try:
            out = sorted({int(x) for x in val if int(x) > 1})
        except Exception:
            out = default
        return out or default

    return {
        'enabled': bool(raw.get('enabled', True)),
        'ma_periods': int_list('ma_periods', [5, 10, 20, 60]),
        'support_windows': int_list('support_windows', [20, 60]),
        'break_tolerance_pct': abs(pct_value('break_tolerance_pct', 0.005)),
        'near_support_pct': abs(pct_value('near_support_pct', 0.01)),
        'fetch_days': int(raw.get('fetch_days', 100) or 100),
        'min_points': int(raw.get('min_points', 20) or 20),
    }


def fetch_position_kline(stock_code: str, target_date: date | None = None, days: int = 100):
    """Fetch qfq daily K-line for a held A-share position via akshare.

    Kept as a tiny wrapper so tests can inject deterministic K-line data and the
    daily report degrades gracefully when network/vendor data is unavailable.
    """
    import akshare as ak

    sym = str(stock_code or '').lower().replace('sh', '').replace('sz', '').replace('bj', '')
    if not sym:
        return None
    end_day = target_date or date.today()
    end = end_day.strftime('%Y%m%d')
    start = (end_day - timedelta(days=max(days * 2, 120))).strftime('%Y%m%d')
    try:
        df = ak.stock_zh_a_hist(symbol=sym, period='daily', start_date=start, end_date=end, adjust='qfq')
    except Exception as exc:
        logger.warning('fetch kline failed for %s: %s', stock_code, exc)
        return None
    if df is None or len(df) == 0:
        return None
    return df.tail(days).reset_index(drop=True)


def _column_values(kline, *names: str) -> list[float]:
    """Return numeric values from a pandas DataFrame or list[dict]."""
    if kline is None:
        return []
    for name in names:
        try:
            if hasattr(kline, 'columns') and name in kline.columns:
                return [float(x) for x in kline[name].dropna().tolist()]
        except Exception:
            pass
    if isinstance(kline, list):
        for name in names:
            vals = []
            for row in kline:
                if isinstance(row, dict) and row.get(name) is not None:
                    try:
                        vals.append(float(row.get(name)))
                    except Exception:
                        continue
            if vals:
                return vals
    return []


def analyze_position_technical_break(position: dict, kline, thresholds: dict | None = None) -> dict:
    """Analyze whether one held stock has broken key MAs/support levels.

    Returns a structured result for report rendering.  ``status`` is one of:
    ok / warn / critical / unavailable.
    """
    thresholds = {**_load_technical_break_thresholds(), **(thresholds or {})}
    code = position.get('stock_code') or position.get('code') or ''
    name = position.get('stock_name') or position.get('name') or code or '未知标的'
    result = {
        'code': code,
        'name': name,
        'status': 'ok',
        'severity': 'ok',
        'price': None,
        'signals': [],
        'levels': {},
        'message': '',
    }

    closes = _column_values(kline, '收盘', 'close', 'Close')
    lows = _column_values(kline, '最低', 'low', 'Low')
    if len(closes) < int(thresholds['min_points']):
        current = position.get('current_price')
        try:
            result['price'] = float(current) if current is not None else None
        except Exception:
            result['price'] = None
        result.update({
            'status': 'unavailable',
            'severity': 'warn',
            'message': f"{name}({code}) K线数据不足，无法判断均线/支撑破位",
        })
        return result

    price = float(closes[-1])
    result['price'] = price
    tol = float(thresholds['break_tolerance_pct'])
    near = float(thresholds['near_support_pct'])

    critical = False
    warn = False
    for period in thresholds['ma_periods']:
        if len(closes) < period:
            continue
        ma = sum(closes[-period:]) / period
        result['levels'][f'MA{period}'] = ma
        if price < ma * (1 - tol):
            drop = (price / ma - 1) * 100
            if period >= 20:
                critical = True
                label = '关键均线'
            else:
                warn = True
                label = '短期均线'
            result['signals'].append(f"跌破{label}MA{period} {ma:.2f}（{drop:.1f}%）")

    # Support is previous N-day low, excluding the current bar to avoid a new low
    # masking its own breakdown.
    for window in thresholds['support_windows']:
        if len(lows) <= window:
            continue
        prev_lows = lows[-(window + 1):-1]
        if not prev_lows:
            continue
        support = min(prev_lows)
        result['levels'][f'{window}日支撑'] = support
        if price < support * (1 - tol):
            critical = True
            drop = (price / support - 1) * 100
            result['signals'].append(f"跌破{window}日低点支撑 {support:.2f}（{drop:.1f}%）")
        elif price <= support * (1 + near):
            warn = True
            dist = (price / support - 1) * 100
            result['signals'].append(f"贴近{window}日低点支撑 {support:.2f}（+{dist:.1f}%）")

    if critical:
        result['status'] = result['severity'] = 'critical'
    elif warn:
        result['status'] = result['severity'] = 'warn'
    else:
        result['message'] = f"{name}({code}) 未见明显均线/支撑破位"
        return result

    result['message'] = f"{name}({code}) 现价 {price:.2f}：" + '；'.join(result['signals'])
    return result


def detect_position_technical_breaks(
    positions: list[dict],
    target_date: date | None = None,
    kline_fetcher=None,
    thresholds: dict | None = None,
) -> list[dict]:
    """Analyze all current positions for MA/support breakdowns (REQ-025)."""
    thresholds = {**_load_technical_break_thresholds(), **(thresholds or {})}
    if not thresholds.get('enabled', True):
        return []
    fetcher = kline_fetcher or fetch_position_kline
    analyses: list[dict] = []
    for p in positions or []:
        try:
            qty = int(p.get('quantity') or 0)
        except Exception:
            qty = 0
        if qty <= 0:
            continue
        code = p.get('stock_code') or p.get('code') or ''
        try:
            kline = fetcher(code, target_date, int(thresholds['fetch_days']))
        except TypeError:
            kline = fetcher(code)
        except Exception as exc:
            logger.warning('technical break fetcher failed for %s: %s', code, exc)
            kline = None
        analyses.append(analyze_position_technical_break(p, kline, thresholds))
    return analyses


def format_position_technical_breaks(analyses: list[dict], compact: bool = False, limit: int | None = None) -> str:
    """Render REQ-025 technical-break analysis as Markdown."""
    if not analyses:
        return ''
    issues = [a for a in analyses if a.get('status') in ('critical', 'warn')]
    unavailable = [a for a in analyses if a.get('status') == 'unavailable']
    if compact:
        if not issues and not unavailable:
            return ''
        shown = issues[:(limit or 3)]
        lines = ['🧭 技术面破位']
        if unavailable:
            lines.append(f"⚠️ {len(unavailable)} 只K线数据不足，已暂停技术面策略")
    else:
        shown = issues[:(limit or 20)]
        lines = ['### 🧭 持仓技术面破位', '']
        if not issues:
            if unavailable:
                lines.append(f"⚠️ **{len(unavailable)} 只持仓K线数据不足**，已暂停以下持仓的技术面破位监控：")
                for item in unavailable[:5]:
                    lines.append(f"  - {item.get('message','')}")
                lines.append('')
                lines.append('**降级策略**：数据不足期间，暂停均线止损/支撑破位止损，切换为固定止损（-8%）或人工判断。')
            else:
                lines.append('- ✅ 持仓未见明显均线/支撑破位。')
            return '\n'.join(lines)

    for item in shown:
        icon = '🚨' if item.get('status') == 'critical' else '⚠️'
        lines.append(f"- {icon} {item.get('message', '')}")
    if len(issues) > len(shown):
        lines.append(f"- … 另有 {len(issues) - len(shown)} 条，见完整复盘")
    return '\n'.join(lines)


def has_technical_break_issue(analyses: list[dict]) -> bool:
    return any(a.get('status') in ('critical', 'warn') for a in analyses or [])


# =====================================
# 1.1 双账户执行一致性诊断（REQ-034）
# =====================================
def _money(v) -> str:
    try:
        return f"¥{float(v):,.0f}"
    except Exception:
        return "¥0"


def _pct(v) -> str:
    try:
        return f"{float(v) * 100:.1f}%"
    except Exception:
        return "0.0%"


def _account_metrics(account_id: int, target_date: date) -> dict:
    """汇总单账户当日执行、持仓与资金利用率，用于 sim/live 对账。"""
    account = fetch_account(account_id) or {}
    positions = fetch_positions(account_id)
    trades = fetch_trades(account_id, target_date)
    market_value = sum(float(p.get('market_value') or 0) for p in positions)
    cash = float(account.get('cash') or 0)
    total_value = market_value + cash
    trade_amount = sum(float(t.get('amount') or (float(t.get('price') or 0) * int(t.get('quantity') or 0))) for t in trades)
    buy_count = sum(1 for t in trades if t.get('direction') == 'BUY')
    sell_count = sum(1 for t in trades if t.get('direction') == 'SELL')
    broker_counts = defaultdict(int)
    for t in trades:
        broker_counts[t.get('broker') or 'unknown'] += 1
    return {
        'account': account,
        'positions': positions,
        'trades': trades,
        'position_codes': {p.get('stock_code') for p in positions if p.get('stock_code')},
        'trade_codes': {t.get('stock_code') for t in trades if t.get('stock_code')},
        'position_count': len([p for p in positions if int(p.get('quantity') or 0) > 0]),
        'trade_count': len(trades),
        'buy_count': buy_count,
        'sell_count': sell_count,
        'market_value': market_value,
        'cash': cash,
        'total_value': total_value,
        'cash_utilization': (market_value / total_value) if total_value > 0 else 0,
        'trade_amount': trade_amount,
        'broker_counts': dict(broker_counts),
    }


def _diagnose_execution_gap(sim_m: dict, live_m: dict, target_date: date) -> dict:
    """对学习模拟账户与真实/QMT镜像账户做差异归因。"""
    cfg = load_config()
    broker_cfg = cfg.get('broker') or {}
    broker_mode = str(os.environ.get('BROKER_MODE') or broker_cfg.get('mode') or 'sim').lower()
    accounts_cfg = cfg.get('accounts') or {}
    learn_cfg = accounts_cfg.get('learn') or {}
    real_cfg = accounts_cfg.get('real') or {}

    only_sim_pos = sorted(sim_m['position_codes'] - live_m['position_codes'])
    only_live_pos = sorted(live_m['position_codes'] - sim_m['position_codes'])
    only_sim_trades = sorted(sim_m['trade_codes'] - live_m['trade_codes'])
    only_live_trades = sorted(live_m['trade_codes'] - sim_m['trade_codes'])

    issues = []
    causes = []
    suggestions = []

    if sim_m['trade_count'] > 0 and live_m['trade_count'] == 0:
        issues.append(f"学习账户当日有 {sim_m['trade_count']} 笔交易，但真实/QMT账户 0 笔成交")
    if sim_m['position_count'] > 0 and live_m['position_count'] == 0:
        issues.append(f"学习账户持仓 {sim_m['position_count']} 只，但真实/QMT账户空仓")
    elif only_sim_pos:
        issues.append(f"仅学习账户持有 {len(only_sim_pos)} 只：{', '.join(only_sim_pos[:8])}{'...' if len(only_sim_pos) > 8 else ''}")
    if only_live_pos:
        issues.append(f"仅真实/QMT账户持有 {len(only_live_pos)} 只：{', '.join(only_live_pos[:8])}{'...' if len(only_live_pos) > 8 else ''}")
    util_gap = sim_m['cash_utilization'] - live_m['cash_utilization']
    if abs(util_gap) >= 0.20:
        issues.append(f"现金利用率差异 {_pct(util_gap)}（学习 {_pct(sim_m['cash_utilization'])} vs 真实/QMT {_pct(live_m['cash_utilization'])}）")

    # 原因分类：按最可能、最可行动的顺序给出。
    if broker_mode in ('sim', 'paper', 'mock', 'backtest'):
        causes.append('未开启实盘：config.yaml broker.mode 当前为 sim，策略只写模拟成交')
        suggestions.append('若确认要联动 QMT，先把 broker.mode 切到 qmt/live，并在小额白名单内验证')
    if real_cfg and not bool(real_cfg.get('auto_trade', False)):
        causes.append('账户配置差异：accounts.real.auto_trade=false，真实账户定位为持仓镜像/复盘，不自动跟单')
        suggestions.append('如需真实账户自动执行，必须显式启用 real.auto_trade 并配置风控上限')
    if sim_m['trade_count'] > 0 and not any(str(k).lower() == 'qmt' for k in sim_m.get('broker_counts', {})):
        causes.append('下单通道差异：当日成交 broker 不是 qmt，未发现 QMT 订单落库')
        suggestions.append('检查 gateways/qmt_config.json、QMT 客户端登录状态和 NOTIFIER/交易 dry_run 配置')
    if sim_m['trade_count'] > 0 and live_m['trade_count'] == 0 and broker_mode not in ('sim', 'paper', 'mock', 'backtest'):
        causes.append('可能下单失败/风控拦截/同步延迟：策略有信号但真实账户未出现成交')
        suggestions.append('查看 output/vqlearn_live.log、QMT 委托/废单记录和风控日志，确认订单是否被拒')
    if only_sim_trades and live_m['trade_count'] > 0:
        causes.append('策略执行差异：sim 与真实/QMT当日交易标的不同')
        suggestions.append('对比两账户 stock_pool、资金规模、仓位上限、黑白名单与风控参数')
    if not issues:
        issues.append('未发现显著执行差异')
        causes.append('sim 与真实/QMT账户在持仓、交易、资金利用率上基本一致')
        suggestions.append('继续观察下一交易日复盘')

    # 去重但保持顺序
    def dedupe(items):
        seen = set(); out = []
        for x in items:
            if x and x not in seen:
                seen.add(x); out.append(x)
        return out

    return {
        'date': target_date.isoformat(),
        'broker_mode': broker_mode,
        'learn_auto_trade': bool(learn_cfg.get('auto_trade', False)),
        'real_auto_trade': bool(real_cfg.get('auto_trade', False)),
        'only_sim_pos': only_sim_pos,
        'only_live_pos': only_live_pos,
        'only_sim_trades': only_sim_trades,
        'only_live_trades': only_live_trades,
        'issues': dedupe(issues),
        'causes': dedupe(causes),
        'suggestions': dedupe(suggestions),
    }


def analyze_execution_consistency(target_date: date) -> dict:
    """REQ-034：生成双账户执行一致性诊断数据结构。"""
    sim_m = _account_metrics(1, target_date)
    live_m = _account_metrics(2, target_date)
    diag = _diagnose_execution_gap(sim_m, live_m, target_date)
    return {'sim': sim_m, 'live': live_m, 'diagnosis': diag}


def render_execution_consistency_section(target_date: date, compact: bool = False) -> str:
    """渲染双账户一致性诊断 Markdown，完整复盘与企微摘要共用。"""
    data = analyze_execution_consistency(target_date)
    sim_m, live_m, diag = data['sim'], data['live'], data['diagnosis']

    lines = ['## 🧭 双账户执行一致性诊断']
    lines.append('')
    lines.append(f"执行模式：`{diag['broker_mode']}` | 学习自动交易：{diag['learn_auto_trade']} | 真实自动交易：{diag['real_auto_trade']}")
    lines.append('')
    lines.append(
        f"- 学习/sim：持仓 {sim_m['position_count']} 只，今日交易 {sim_m['trade_count']} 笔"
        f"（买 {sim_m['buy_count']} / 卖 {sim_m['sell_count']}），资金利用率 {_pct(sim_m['cash_utilization'])}，成交额 {_money(sim_m['trade_amount'])}"
    )
    lines.append(
        f"- 真实/QMT：持仓 {live_m['position_count']} 只，今日交易 {live_m['trade_count']} 笔"
        f"（买 {live_m['buy_count']} / 卖 {live_m['sell_count']}），资金利用率 {_pct(live_m['cash_utilization'])}，成交额 {_money(live_m['trade_amount'])}"
    )
    lines.append('')

    if compact:
        lines.append('**结论/归因：** ' + '；'.join(diag['causes'][:2]))
        lines.append('**建议：** ' + '；'.join(diag['suggestions'][:2]))
        # 附加快速操作提示（企微摘要专用）
        if diag.get('real_auto_trade') is False and diag.get('broker_mode') == 'sim':
            lines.append('> 💡 如需开启真实账户自动跟单，详见 `docs/real-trading-setup.md`')
        return '\n'.join(lines)

    lines.append('### 差异')
    for issue in diag['issues']:
        lines.append(f"- ⚠️ {issue}")
    lines.append('')
    lines.append('### 原因分类')
    for cause in diag['causes']:
        lines.append(f"- {cause}")
    lines.append('')
    lines.append('### 下一步建议')
    for s in diag['suggestions']:
        lines.append(f"- {s}")
    lines.append('')
    return '\n'.join(lines)


def _parse_signal_detail(raw):
    """解析 sim_trades.signal_detail，兼容 JSON 字符串/字典/空值。"""
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        import json
        try:
            val = json.loads(text)
        except Exception:
            return {"raw": text}
        return val if isinstance(val, dict) else {"raw": text}
    return None


def render_signal_detail_lines(detail) -> list[str]:
    """REQ-032：把完整信号解释渲染为可折叠 Markdown/HTML 片段。"""
    detail = _parse_signal_detail(detail)
    if not detail:
        return []

    rules = detail.get('triggered_rules') or []
    indicators = detail.get('indicators_snapshot') or {}
    price_snapshot = detail.get('price_snapshot') or {}
    strategy_version = detail.get('strategy_version') or ''
    trigger_type = detail.get('trigger_type') or detail.get('signal') or '触发详情'
    summary = ' | '.join((r.get('rule') or r.get('indicator') or '')[:24] for r in rules[:3] if isinstance(r, dict))

    lines = ['<details>']
    lines.append(f'<summary>📋 查看完整信号解释（{summary or trigger_type}）</summary>')
    if strategy_version:
        lines.append(f'- 策略版本: `{strategy_version}`')
    if trigger_type:
        lines.append(f'- 触发类型: `{trigger_type}`')
    if rules:
        lines.append('- 触发规则:')
        for r in rules[:10]:
            if not isinstance(r, dict):
                lines.append(f'  - {r}')
                continue
            cur = r.get('current_value')
            th = r.get('threshold')
            op = r.get('operator', '?')
            cur_text = f'{cur:.4f}' if isinstance(cur, (int, float)) else str(cur)
            th_text = f'{th:.4f}' if isinstance(th, (int, float)) else str(th)
            lines.append(f"  - {r.get('rule') or r.get('indicator') or 'rule'}: 当前值 {cur_text} {op} 阈值 {th_text}")
    if indicators:
        compact = ', '.join(f'{k}={v}' for k, v in indicators.items() if v is not None)
        lines.append(f'- 指标快照: {compact[:600]}')
    if price_snapshot:
        compact = ', '.join(f'{k}={v}' for k, v in price_snapshot.items() if v is not None)
        lines.append(f'- 行情快照: {compact[:300]}')
    if detail.get('timestamp'):
        lines.append(f"- 信号时间: `{detail['timestamp']}`")
    if detail.get('raw'):
        lines.append(f"```text\n{detail['raw'][:1000]}\n```")
    lines.append('</details>')
    return lines



def _extract_entry_strategy_tag(signal_reason: str | None, signal_detail=None) -> tuple[str, str]:
    """Return (source_type, strategy_tag) for an entry snapshot (REQ-029).

    The daily review is the first place where manual initial positions and auto
    buy signals meet.  Normalising both into a stable tag lets later analysis
    compare the user's real/manual entries with strategy generated entries.
    """
    reason = (signal_reason or '').strip()
    detail = _parse_signal_detail(signal_detail) or {}
    lower = reason.lower()

    # Manual / imported real-position entries.
    if '初始化建仓快照' in reason or '初始持仓回填' in reason or '初始持仓' in reason:
        return 'manual_initial_snapshot', 'user_real_position'
    if '手动' in reason or '用户实盘' in reason:
        return 'manual_user_action', 'user_manual'

    # Structured signal detail has priority when present.
    for key in ('strategy_tag', 'trigger_type', 'signal'):
        val = detail.get(key) if isinstance(detail, dict) else None
        if val:
            tag = str(val).strip().lower()
            if tag in {'buy', 'tech_buy'}:
                continue
            return 'auto_strategy', tag

    # Parse historical short reasons, e.g. "自动: buy_zone | ...".
    import re
    m = re.search(r'自动\s*[:：]\s*([a-zA-Z0-9_\-]+)', reason)
    if m:
        return 'auto_strategy', m.group(1).lower()
    m = re.search(r'\b(buy_[a-zA-Z0-9_\-]+)\b', lower)
    if m:
        return 'auto_strategy', m.group(1).lower()

    return 'unknown_entry', 'unclassified'


def ensure_entry_snapshot_table(conn) -> None:
    """Create/upgrade the structured entry snapshot table (REQ-029)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS position_entry_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            source_trade_id INTEGER NOT NULL,
            entry_date DATE,
            stock_code TEXT,
            stock_name TEXT,
            source_type TEXT,
            strategy_tag TEXT,
            entry_price REAL,
            entry_quantity INTEGER,
            entry_amount REAL,
            current_price REAL,
            current_quantity INTEGER DEFAULT 0,
            floating_pnl REAL DEFAULT 0,
            floating_pnl_pct REAL DEFAULT 0,
            status TEXT DEFAULT 'open',
            signal_reason TEXT,
            raw_detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, source_trade_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entry_snapshots_account_date ON position_entry_snapshots(account_id, entry_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entry_snapshots_strategy ON position_entry_snapshots(source_type, strategy_tag)")


def extract_entry_snapshots(account_id: int, target_date: date, conn_factory=get_conn) -> list[dict]:
    """Extract BUY entries up to target_date into structured snapshots (REQ-029).

    It supports both sides of the dual-account review:
    - real account imported entries such as "初始持仓回填" / "初始化建仓快照";
    - learning-account automatic entries such as "自动: buy_zone".
    """
    conn = conn_factory()
    conn.row_factory = sqlite3.Row
    try:
        ensure_entry_snapshot_table(conn)
        trades = conn.execute(
            """
            SELECT * FROM sim_trades
             WHERE account_id=? AND direction='BUY' AND trade_date<=?
             ORDER BY trade_date, id
            """,
            (account_id, target_date.isoformat()),
        ).fetchall()
        positions = {
            r['stock_code']: r for r in conn.execute(
                "SELECT * FROM sim_positions WHERE account_id=?",
                (account_id,),
            ).fetchall()
        }
        snapshots: list[dict] = []
        remaining_by_code = {code: int(pos['quantity'] or 0) for code, pos in positions.items()}
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for t in trades:
            reason = t['signal_reason'] if 'signal_reason' in t.keys() else ''
            detail = t['signal_detail'] if 'signal_detail' in t.keys() else None
            source_type, strategy_tag = _extract_entry_strategy_tag(reason, detail)
            code = t['stock_code']
            pos = positions.get(code)
            qty = int(t['quantity'] or 0)
            entry_price = float(t['price'] or 0)
            remaining = remaining_by_code.get(code, 0)
            cur_price = float((pos['current_price'] if pos else None) or entry_price or 0)
            open_qty = min(qty, remaining) if remaining > 0 else 0
            remaining_by_code[code] = max(0, remaining - open_qty)
            floating_pnl = (cur_price - entry_price) * open_qty if open_qty and entry_price else 0.0
            floating_pnl_pct = ((cur_price / entry_price - 1) * 100) if open_qty and entry_price else 0.0
            status = 'open' if open_qty >= qty and qty > 0 else ('partial_or_closed' if open_qty > 0 else 'closed_or_absent')
            entry_amount = float((t['amount'] if 'amount' in t.keys() else None) or entry_price * qty)
            raw_detail = detail if isinstance(detail, str) else None
            row = {
                'account_id': account_id,
                'source_trade_id': int(t['id']),
                'entry_date': t['trade_date'],
                'stock_code': t['stock_code'],
                'stock_name': t['stock_name'],
                'source_type': source_type,
                'strategy_tag': strategy_tag,
                'entry_price': entry_price,
                'entry_quantity': qty,
                'entry_amount': entry_amount,
                'current_price': cur_price,
                'current_quantity': open_qty,
                'floating_pnl': floating_pnl,
                'floating_pnl_pct': floating_pnl_pct,
                'status': status,
                'signal_reason': reason,
                'raw_detail': raw_detail,
            }
            conn.execute(
                """
                INSERT INTO position_entry_snapshots (
                    account_id, source_trade_id, entry_date, stock_code, stock_name,
                    source_type, strategy_tag, entry_price, entry_quantity, entry_amount,
                    current_price, current_quantity, floating_pnl, floating_pnl_pct,
                    status, signal_reason, raw_detail, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, source_trade_id) DO UPDATE SET
                    entry_date=excluded.entry_date,
                    stock_code=excluded.stock_code,
                    stock_name=excluded.stock_name,
                    source_type=excluded.source_type,
                    strategy_tag=excluded.strategy_tag,
                    entry_price=excluded.entry_price,
                    entry_quantity=excluded.entry_quantity,
                    entry_amount=excluded.entry_amount,
                    current_price=excluded.current_price,
                    current_quantity=excluded.current_quantity,
                    floating_pnl=excluded.floating_pnl,
                    floating_pnl_pct=excluded.floating_pnl_pct,
                    status=excluded.status,
                    signal_reason=excluded.signal_reason,
                    raw_detail=excluded.raw_detail,
                    updated_at=excluded.updated_at
                """,
                (
                    row['account_id'], row['source_trade_id'], row['entry_date'], row['stock_code'], row['stock_name'],
                    row['source_type'], row['strategy_tag'], row['entry_price'], row['entry_quantity'], row['entry_amount'],
                    row['current_price'], row['current_quantity'], row['floating_pnl'], row['floating_pnl_pct'],
                    row['status'], row['signal_reason'], row['raw_detail'], now,
                ),
            )
            snapshots.append(row)
        conn.commit()
        return snapshots
    finally:
        conn.close()


def render_entry_strategy_snapshot_section(account_id: int, target_date: date, compact: bool = False) -> str:
    """Render manual-vs-auto entry preference summary from extracted snapshots."""
    snapshots = extract_entry_snapshots(account_id, target_date)
    if not snapshots:
        return ''

    groups: dict[tuple[str, str], dict] = {}
    for s in snapshots:
        key = (s['source_type'], s['strategy_tag'])
        g = groups.setdefault(key, {
            'count': 0,
            'open_count': 0,
            'qty': 0,
            'amount': 0.0,
            'floating_pnl': 0.0,
            'weighted_pct': 0.0,
            'examples': [],
        })
        g['count'] += 1
        g['open_count'] += 1 if s['current_quantity'] > 0 else 0
        g['qty'] += int(s['entry_quantity'] or 0)
        g['amount'] += float(s['entry_amount'] or 0)
        g['floating_pnl'] += float(s['floating_pnl'] or 0)
        if s['current_quantity'] > 0 and s['entry_price']:
            weight = float(s['entry_amount'] or 0)
            g['weighted_pct'] += float(s['floating_pnl_pct'] or 0) * weight
        if len(g['examples']) < (2 if compact else 4):
            g['examples'].append(f"{s['stock_name']}({s['stock_code']}) {s['entry_date']}")

    lines = ['### 🧬 建仓快照与策略标签']
    if compact:
        best = sorted(groups.items(), key=lambda kv: kv[1]['floating_pnl'], reverse=True)[:3]
        for (source_type, strategy_tag), g in best:
            avg_pct = g['weighted_pct'] / g['amount'] if g['amount'] else 0.0
            lines.append(f"- {strategy_tag}: {g['count']} 笔 / 持有 {g['open_count']} 笔，浮盈亏 {g['floating_pnl']:+,.0f}（均 {avg_pct:+.2f}%）")
        return '\n'.join(lines)

    lines.append('| 来源 | 策略标签 | 笔数 | 仍持有 | 成本金额 | 当前浮盈亏 | 均值 | 示例 |')
    lines.append('|---|---|---:|---:|---:|---:|---:|---|')
    for (source_type, strategy_tag), g in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        avg_pct = g['weighted_pct'] / g['amount'] if g['amount'] else 0.0
        examples = '；'.join(g['examples'])
        lines.append(
            f"| {source_type} | `{strategy_tag}` | {g['count']} | {g['open_count']} | "
            f"¥{g['amount']:,.0f} | {g['floating_pnl']:+,.0f} | {avg_pct:+.2f}% | {examples} |"
        )
    lines.append('')
    lines.append('> 用途：把用户真实持仓的初始化建仓与自动 buy_zone/buy_strong 信号统一沉淀，后续可直接按策略标签评估手动/自动建仓收益偏好。')
    return '\n'.join(lines)

# =====================================
# 2. 实现盈亏 (FIFO 配对)
# =====================================
def compute_realized_pnl(account_id: int, target_date: date):
    """FIFO 配对当日 SELL 与历史 BUY，算实现盈亏（卖出价 - 平均买入成本）* 数量 - 双向手续费"""
    c = get_conn()
    # 拉所有历史交易（截至当日）
    rows = c.execute(
        '''SELECT * FROM sim_trades WHERE account_id=? AND trade_date<=? ORDER BY trade_date, id''',
        (account_id, target_date.isoformat())
    ).fetchall()
    c.close()

    # 按股票代码分组，FIFO 队列
    queues = defaultdict(list)  # code -> [(qty, price, fee_per_share)]
    realized_today = []  # 当日卖出每笔实现 pnl

    for r in rows:
        code = r['stock_code']
        d = r['direction']
        qty = r['quantity']
        price = r['price']
        fee = (r['commission'] or 0) + (r['tax'] or 0)
        fee_per = fee / qty if qty else 0
        is_today = (r['trade_date'] == target_date.isoformat())

        if d == 'BUY':
            queues[code].append([qty, price, fee_per])
        elif d == 'SELL':
            remaining = qty
            cost_total = 0.0
            buy_fee_total = 0.0
            while remaining > 0 and queues[code]:
                head = queues[code][0]
                take = min(head[0], remaining)
                cost_total += take * head[1]
                buy_fee_total += take * head[2]
                head[0] -= take
                remaining -= take
                if head[0] == 0:
                    queues[code].pop(0)

            if is_today:
                consumed = qty - remaining
                if consumed > 0:
                    sell_amount = consumed * price
                    sell_fee = fee * (consumed / qty)
                    pnl = sell_amount - cost_total - buy_fee_total - sell_fee
                    pnl_pct = (price / (cost_total / consumed) - 1) * 100 if cost_total > 0 else 0
                    try:
                        sr = r['signal_reason'] or ''
                    except (IndexError, KeyError):
                        sr = ''
                    realized_today.append({
                        'code': code,
                        'name': r['stock_name'],
                        'qty': consumed,
                        'sell_price': price,
                        'avg_cost': cost_total / consumed if consumed > 0 else 0,
                        'pnl': pnl,
                        'pnl_pct': pnl_pct,
                        'signal_reason': sr,
                    })

    return realized_today


# =====================================
# 3. nav 写入 + 计算
# =====================================
def write_daily_nav(account_id: int, target_date: date, account: dict, positions: list, initial_cash: float | None = None, pause_daily_return: bool = False):
    market_value = sum(p['market_value'] for p in positions)
    total_value = market_value + account['cash']
    # 优先用传入的 initial_cash，否则从 account dict 取
    if initial_cash is None:
        initial_cash = account.get('initial_cash') or 100000.0
    initial = initial_cash
    cumulative_return = (total_value / initial - 1) * 100

    c = get_conn()
    last = c.execute(
        '''SELECT total_value FROM sim_daily_nav 
           WHERE account_id=? AND trade_date < ? 
           ORDER BY trade_date DESC LIMIT 1''',
        (account_id, target_date.isoformat())
    ).fetchone()
    prev_value = last['total_value'] if last else initial
    daily_return = None if pause_daily_return else ((total_value / prev_value - 1) * 100 if prev_value > 0 else 0)

    # 最大回撤
    all_navs = c.execute(
        'SELECT total_value FROM sim_daily_nav WHERE account_id=? ORDER BY trade_date',
        (account_id,)
    ).fetchall()
    peak = initial
    for r in all_navs:
        peak = max(peak, r['total_value'])
    peak = max(peak, total_value)
    max_drawdown = (total_value / peak - 1) * 100

    c.execute(
        '''INSERT OR REPLACE INTO sim_daily_nav 
           (account_id, trade_date, total_value, cash, market_value, daily_return, cumulative_return, max_drawdown)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (account_id, target_date.isoformat(), total_value, account['cash'], market_value,
         daily_return, cumulative_return, max_drawdown)
    )
    c.commit()
    c.close()

    return {
        'total_value': total_value,
        'cash': account['cash'],
        'market_value': market_value,
        'daily_return': daily_return,
        'cumulative_return': cumulative_return,
        'max_drawdown': max_drawdown,
        'prev_value': prev_value,
    }


# =====================================
# 4. 策略绩效指标（REQ-014）
# =====================================
def compute_realized_pnl_until(account_id: int, target_date: date) -> list[dict]:
    """FIFO 配对截至 target_date 的全部 SELL，用于计算历史胜率。"""
    c = get_conn()
    rows = c.execute(
        '''SELECT * FROM sim_trades WHERE account_id=? AND trade_date<=? ORDER BY trade_date, id''',
        (account_id, target_date.isoformat())
    ).fetchall()
    c.close()

    queues = defaultdict(list)  # code -> [(qty, price, fee_per_share)]
    realized: list[dict] = []

    for r in rows:
        code = r['stock_code']
        direction = r['direction']
        qty = int(r['quantity'] or 0)
        price = float(r['price'] or 0)
        fee = float(r['commission'] or 0) + float(r['tax'] or 0)
        fee_per = fee / qty if qty else 0

        if direction == 'BUY':
            queues[code].append([qty, price, fee_per])
        elif direction == 'SELL':
            remaining = qty
            cost_total = 0.0
            buy_fee_total = 0.0
            while remaining > 0 and queues[code]:
                head = queues[code][0]
                take = min(head[0], remaining)
                cost_total += take * head[1]
                buy_fee_total += take * head[2]
                head[0] -= take
                remaining -= take
                if head[0] == 0:
                    queues[code].pop(0)

            consumed = qty - remaining
            if consumed <= 0:
                continue
            sell_amount = consumed * price
            sell_fee = fee * (consumed / qty) if qty else 0
            pnl = sell_amount - cost_total - buy_fee_total - sell_fee
            realized.append({
                'trade_date': r['trade_date'],
                'code': code,
                'name': r['stock_name'],
                'qty': consumed,
                'pnl': pnl,
                'pnl_pct': (price / (cost_total / consumed) - 1) * 100 if cost_total > 0 else 0,
            })

    return realized


def calculate_strategy_performance(account_id: int, target_date: date) -> dict:
    """基于 sim_daily_nav 资产曲线 + FIFO 平仓结果计算策略级绩效。"""
    c = get_conn()
    rows = c.execute(
        '''SELECT trade_date, total_value, daily_return
           FROM sim_daily_nav
           WHERE account_id=? AND trade_date<=?
           ORDER BY trade_date''',
        (account_id, target_date.isoformat())
    ).fetchall()
    c.close()

    equity_curve = [float(r['total_value'] or 0) for r in rows if float(r['total_value'] or 0) > 0]
    max_drawdown = 0.0
    if equity_curve:
        peak = equity_curve[0]
        for value in equity_curve:
            peak = max(peak, value)
            if peak > 0:
                max_drawdown = min(max_drawdown, value / peak - 1)

    daily_returns = []
    for r in rows:
        dr = r['daily_return']
        if dr is None:
            continue
        daily_returns.append(float(dr) / 100.0)

    sharpe = None
    volatility = None
    avg_daily_return = None
    if daily_returns:
        avg_daily_return = sum(daily_returns) / len(daily_returns)
    if len(daily_returns) >= 2:
        mean = avg_daily_return or 0.0
        variance = sum((x - mean) ** 2 for x in daily_returns) / (len(daily_returns) - 1)
        std = sqrt(variance)
        volatility = std * sqrt(252)
        sharpe = (mean / std) * sqrt(252) if std > 0 else None

    from sim.closed_trades import analyze_closed_trades
    closed_summary = analyze_closed_trades(account_id, target_date, conn_factory=get_conn)['summary']
    closed_count = closed_summary['closed_count']
    win_count = closed_summary['win_count']
    loss_count = closed_summary['loss_count']
    win_rate = (win_count / closed_count) if closed_count else None
    profit_factor = closed_summary['profit_factor']

    return {
        'nav_days': len(rows),
        'return_days': len(daily_returns),
        'max_drawdown': max_drawdown * 100,
        'sharpe': sharpe,
        'annualized_volatility': volatility * 100 if volatility is not None else None,
        'avg_daily_return': avg_daily_return * 100 if avg_daily_return is not None else None,
        'closed_trades': closed_count,
        'win_count': win_count,
        'loss_count': loss_count,
        'win_rate': win_rate * 100 if win_rate is not None else None,
        'profit_factor': profit_factor,
    }




def calculate_pnl_contribution(positions: list[dict], realized: list[dict], total_value: float | None = None) -> list[dict]:
    """Aggregate per-stock contribution to account PnL for review attribution (REQ-021).

    The daily review already shows raw holdings and realized sells separately.  This helper
    combines both dimensions into a single attribution list so users can immediately see
    which symbols are driving account profit/loss.
    """
    by_code: dict[str, dict] = {}

    def entry(code: str, name: str = '') -> dict:
        key = code or 'UNKNOWN'
        if key not in by_code:
            by_code[key] = {
                'code': key,
                'name': name or key,
                'quantity': 0,
                'market_value': 0.0,
                'floating_pnl': 0.0,
                'realized_pnl': 0.0,
                'total_pnl': 0.0,
                'abs_contribution_pct': 0.0,
                'total_value_pct': 0.0,
            }
        elif name and by_code[key]['name'] == key:
            by_code[key]['name'] = name
        return by_code[key]

    for p in positions or []:
        e = entry(str(p.get('stock_code') or ''), str(p.get('stock_name') or ''))
        e['quantity'] += int(p.get('quantity') or 0)
        e['market_value'] += float(p.get('market_value') or 0)
        e['floating_pnl'] += float(p.get('pnl') or 0)

    for r in realized or []:
        e = entry(str(r.get('code') or r.get('stock_code') or ''), str(r.get('name') or r.get('stock_name') or ''))
        e['realized_pnl'] += float(r.get('pnl') or 0)

    rows = list(by_code.values())
    for row in rows:
        row['total_pnl'] = row['floating_pnl'] + row['realized_pnl']

    abs_total = sum(abs(r['total_pnl']) for r in rows)
    for row in rows:
        row['abs_contribution_pct'] = (abs(row['total_pnl']) / abs_total * 100.0) if abs_total else 0.0
        row['total_value_pct'] = (row['total_pnl'] / float(total_value) * 100.0) if total_value else 0.0

    rows.sort(key=lambda r: (abs(r['total_pnl']), abs(r['floating_pnl']), r['market_value']), reverse=True)
    return rows


def render_pnl_contribution_section(positions: list[dict], realized: list[dict], total_value: float | None = None, compact: bool = False) -> str:
    """Render account PnL attribution distribution for full report and WeCom summary."""
    rows = calculate_pnl_contribution(positions, realized, total_value)
    rows = [r for r in rows if abs(r['total_pnl']) > 1e-9 or abs(r['floating_pnl']) > 1e-9 or abs(r['realized_pnl']) > 1e-9]
    if not rows:
        return ''

    net = sum(r['total_pnl'] for r in rows)
    profit = sum(r['total_pnl'] for r in rows if r['total_pnl'] > 0)
    loss = sum(r['total_pnl'] for r in rows if r['total_pnl'] < 0)

    if compact:
        lines = [f"🧭 盈亏归因：净 {net:+,.0f}（盈利 {profit:+,.0f} / 亏损 {loss:+,.0f}）"]
        for r in rows[:3]:
            emoji = '🟢' if r['total_pnl'] >= 0 else '🔴'
            lines.append(
                f"  {emoji} {r['name']} {r['total_pnl']:+,.0f} "
                f"(浮 {r['floating_pnl']:+,.0f} / 实 {r['realized_pnl']:+,.0f}, 贡献 {r['abs_contribution_pct']:.1f}%)"
            )
        if len(rows) > 3:
            lines.append(f"  … 其余 {len(rows) - 3} 只合计 {sum(r['total_pnl'] for r in rows[3:]):+,.0f}")
        return '\n'.join(lines)

    lines = ['### 🧭 账户盈亏归因分布']
    lines.append(f"- 净贡献：**{net:+,.2f}**；盈利贡献 {profit:+,.2f} / 亏损贡献 {loss:+,.2f}")
    lines.append('- 口径：当前持仓浮动盈亏 + 当日已实现盈亏；贡献占比按绝对盈亏贡献计算，避免正负抵消。')
    lines.append('')
    lines.append('| 股票 | 持仓市值 | 浮动盈亏 | 当日实现 | 合计贡献 | 贡献占比 | 占总资产 |')
    lines.append('|---|---:|---:|---:|---:|---:|---:|')
    for r in rows:
        lines.append(
            f"| {r['name']} ({r['code']}) | ¥{r['market_value']:,.0f} | "
            f"{r['floating_pnl']:+,.2f} | {r['realized_pnl']:+,.2f} | "
            f"**{r['total_pnl']:+,.2f}** | {r['abs_contribution_pct']:.1f}% | {r['total_value_pct']:+.2f}% |"
        )
    lines.append('')
    return '\n'.join(lines)

def _fmt_metric(value, suffix='', digits=2, none_text='样本不足') -> str:
    if value is None:
        return none_text
    if value == float('inf'):
        return '∞'
    return f"{value:.{digits}f}{suffix}"


def render_strategy_performance_section(account_id: int, target_date: date, compact: bool = False) -> str:
    """渲染策略级绩效指标（最大回撤/夏普/胜率等）。"""
    m = calculate_strategy_performance(account_id, target_date)
    win_rate_text = _fmt_metric(m['win_rate'], '%')
    sharpe_text = _fmt_metric(m['sharpe'])
    mdd_text = _fmt_metric(m['max_drawdown'], '%')

    if compact:
        return (
            f"📐 绩效：最大回撤 {mdd_text} | 夏普 {sharpe_text} | "
            f"胜率 {win_rate_text}（{m['win_count']}/{m['closed_trades']}）"
        )

    lines = ['### 📐 策略绩效指标']
    lines.append(f"- 最大回撤：**{mdd_text}**")
    lines.append(f"- 年化夏普比率：**{sharpe_text}**")
    lines.append(f"- 交易胜率：**{win_rate_text}**（盈利 {m['win_count']} / 平仓 {m['closed_trades']}）")
    lines.append(f"- 年化波动率：{_fmt_metric(m['annualized_volatility'], '%')}")
    lines.append(f"- 平均日收益：{_fmt_metric(m['avg_daily_return'], '%')}")
    lines.append(f"- 盈亏比（Profit Factor）：{_fmt_metric(m['profit_factor'])}")
    lines.append(f"- 统计样本：{m['nav_days']} 个净值日 / {m['return_days']} 个有效日收益 / {m['closed_trades']} 笔已平仓交易")
    lines.append('')
    return '\n'.join(lines)


def render_signal_performance_section(account_id: int, target_date: date, compact: bool = False) -> str:
    """REQ-030：按开仓信号统计已平仓交易盈亏，用于验证信号有效性。"""
    from sim.signal_performance import analyze_signal_performance

    data = analyze_signal_performance(account_id, target_date, conn_factory=get_conn, limit=5 if compact else None)
    s = data['summary']
    rows = s.get('by_signal') or []
    if not rows:
        return ''

    def pf_text(v) -> str:
        return _fmt_metric(v, digits=2)

    if compact:
        lines = [
            f"🎯 信号盈亏：{s['segment_count']} 段，净实现 {s['net_pnl']:+,.0f}，覆盖 {s['signal_count']} 类信号"
        ]
        for r in rows[:3]:
            emoji = '🟢' if float(r.get('net_pnl') or 0) >= 0 else '🔴'
            lines.append(
                f"  {emoji} {r['signal']} {r['net_pnl']:+,.0f} | "
                f"胜率 {r['win_rate']:.1f}% ({r['win_count']}/{r['closed_count']}) | PF {pf_text(r.get('profit_factor'))}"
            )
        return '\n'.join(lines)

    lines = ['### 🎯 信号触发交易盈亏统计']
    lines.append(
        f"- 口径：按 FIFO 将已平仓卖出拆分回对应 BUY 批次，并归因到开仓信号；"
        f"共 **{s['segment_count']}** 个平仓片段 / **{s['signal_count']}** 类信号，净实现 **{s['net_pnl']:+,.2f}**。"
    )
    lines.append('- 用途：验证 `buy_zone`、`buy_strong`、右侧确认等信号成交后的真实胜率、盈亏比和收益贡献。')
    lines.append('')
    lines.append('| 开仓信号 | 平仓片段 | 胜率 | 净实现盈亏 | 平均收益率 | Profit Factor | 覆盖标的 |')
    lines.append('|---|---:|---:|---:|---:|---:|---:|')
    for r in rows:
        lines.append(
            f"| `{r['signal']}` | {r['closed_count']} | {r['win_rate']:.1f}% "
            f"({r['win_count']}/{r['closed_count']}) | {r['net_pnl']:+,.2f} | "
            f"{r['avg_pnl_pct']:+.2f}% | {pf_text(r.get('profit_factor'))} | {r['symbol_count']} |"
        )
    lines.append('')
    return '\n'.join(lines)


def render_closed_trades_analysis_section(account_id: int, target_date: date, compact: bool = False) -> str:
    """REQ-023：渲染已平仓历史交易盈亏分析。"""
    from sim.closed_trades import analyze_closed_trades

    data = analyze_closed_trades(account_id, target_date, conn_factory=get_conn, limit=5 if compact else None)
    s = data['summary']
    if not s['closed_count']:
        return ''

    pf = _fmt_metric(s['profit_factor'])
    payoff = _fmt_metric(s['payoff_ratio'])
    avg_hold = _fmt_metric(s['avg_holding_days'], '天', digits=1, none_text='样本不足')
    max_profit = s.get('max_profit_trade') or {}
    max_loss = s.get('max_loss_trade') or {}

    if compact:
        lines = [
            f"🔒 平仓复盘：{s['closed_count']} 笔，胜率 {s['win_rate']:.2f}% | "
            f"净实现 {s['net_pnl']:+,.0f} | 盈亏比 {payoff} | PF {pf}"
        ]
        if max_profit:
            lines.append(f"  🟢 最大盈利 {max_profit.get('stock_name')} {float(max_profit.get('pnl') or 0):+,.0f}")
        if max_loss and float(max_loss.get('pnl') or 0) < 0:
            lines.append(f"  🔴 最大亏损 {max_loss.get('stock_name')} {float(max_loss.get('pnl') or 0):+,.0f}")
        top = s.get('by_symbol') or []
        if top:
            leaders = '；'.join(f"{r['stock_name']} {r['pnl']:+,.0f}" for r in top[:3])
            lines.append(f"  个股贡献：{leaders}")
        return '\n'.join(lines)

    lines = ['### 🔒 已平仓历史交易分析']
    lines.append(
        f"- 平仓笔数：**{s['closed_count']}**；胜率：**{s['win_rate']:.2f}%** "
        f"（盈利 {s['win_count']} / 亏损 {s['loss_count']}）"
    )
    lines.append(
        f"- 累计实现盈亏：**{s['net_pnl']:+,.2f}**；总盈利 {s['gross_profit']:+,.2f} / 总亏损 -{s['gross_loss']:,.2f}"
    )
    lines.append(
        f"- 平均盈利：{s['avg_win']:+,.2f}；平均亏损：{s['avg_loss']:+,.2f}；"
        f"盈亏比：**{payoff}**；Profit Factor：**{pf}**；平均持仓：{avg_hold}"
    )
    if max_profit:
        lines.append(
            f"- 单笔最大盈利：🟢 {max_profit.get('stock_name')}({max_profit.get('stock_code')}) "
            f"{float(max_profit.get('pnl') or 0):+,.2f} / {float(max_profit.get('pnl_pct') or 0):+.2f}% "
            f"（{max_profit.get('close_date')}）"
        )
    if max_loss and float(max_loss.get('pnl') or 0) < 0:
        lines.append(
            f"- 单笔最大亏损：🔴 {max_loss.get('stock_name')}({max_loss.get('stock_code')}) "
            f"{float(max_loss.get('pnl') or 0):+,.2f} / {float(max_loss.get('pnl_pct') or 0):+.2f}% "
            f"（{max_loss.get('close_date')}）"
        )
    lines.append('')
    lines.append('| 个股 | 平仓笔数 | 胜率 | 累计实现盈亏 | 平均收益率 | 卖出金额 |')
    lines.append('|---|---:|---:|---:|---:|---:|')
    for r in (s.get('by_symbol') or [])[:10]:
        lines.append(
            f"| {r['stock_name']} ({r['stock_code']}) | {r['closed_count']} | {r['win_rate']:.1f}% | "
            f"{r['pnl']:+,.2f} | {r['avg_pnl_pct']:+.2f}% | ¥{r['sell_amount']:,.0f} |"
        )
    lines.append('')
    lines.append('最近平仓：')
    for r in data['closed_trades'][:8]:
        emoji = '🟢' if float(r.get('pnl') or 0) >= 0 else '🔴'
        hold = f" / 持仓 {r['holding_days']}天" if r.get('holding_days') is not None else ''
        lines.append(
            f"- {emoji} {r['close_date']} {r['stock_name']}({r['stock_code']}) {r['quantity']}股 "
            f"成本 ¥{float(r['avg_cost']):.3f} → 卖 ¥{float(r['sell_price']):.2f} "
            f"= {float(r['pnl']):+,.2f} ({float(r['pnl_pct']):+.2f}%){hold}"
        )
    lines.append('')
    return '\n'.join(lines)


# =====================================
# 5. 文本生成
# =====================================
def render_account_section(acct: dict, target_date: date, market_snapshot=None) -> str:
    lines = []
    
    # ── REQ-035: 资金口径一致性检测 ──────────────────────
    try:
        from sim.db import detect_cash_discrepancy
        discrepancy = detect_cash_discrepancy(acct['id'])
    except Exception:
        discrepancy = None
    # ──────────────────────────────────────────────────────────

    account = fetch_account(acct['id'])
    # REQ-035: 用 config.yaml 的 initial_cash（而非数据库旧值）计算 nav
    try:
        from sim.config import get_account_config
        cfg = get_account_config(acct['id'])
        config_initial = cfg['initial_cash']
    except Exception:
        config_initial = (account or {}).get('initial_cash', 100000.0)

    if not account:
        # 即使没有账户记录，也要输出口径警告（如果有）
        if discrepancy:
            lines.append(f"## {acct['icon']} {acct['name']}")
            lines.append('')
            lines.append('⚠️ **资金口径异常**：数据库无账户记录，但 config.yaml 中有配置')
            lines.append('')
        return '\n'.join(lines)

    positions = fetch_positions(acct['id'])
    basis_warnings = detect_account_basis_changes(account, positions, target_date, config_initial)
    pause_daily_return = any(w.get('pause_return') for w in basis_warnings)
    trades = fetch_trades(acct['id'], target_date)
    realized = compute_realized_pnl(acct['id'], target_date)
    nav = write_daily_nav(
        acct['id'], target_date, account, positions,
        initial_cash=config_initial,
        pause_daily_return=pause_daily_return,
    )

    realized_pnl = sum(r['pnl'] for r in realized)
    floating_pnl = sum(p['pnl'] for p in positions)
    review_alerts = detect_trade_anomaly_alerts(account, positions, trades, realized, nav, target_date)
    technical_breaks = detect_position_technical_breaks(positions, target_date)
    allocation = summarize_allocation(
        account,
        positions,
        fetch_recent_entry_trades(acct['id']),
        market_snapshot if market_snapshot is not None else fetch_market_sentiment(target_date),
        load_config(),
    )

    # 标题行（如有口径问题、交易异动或技术破位，加警告图标）
    title_prefix = '⚠️ ' if (basis_warnings or review_alerts or has_technical_break_issue(technical_breaks)) else ''
    lines.append(f"## {title_prefix}{acct['icon']} {acct['name']}")
    lines.append('')

    # 口径变更警告（放在最显眼的位置）
    warning_block = format_basis_change_warnings(basis_warnings)
    if warning_block:
        lines.append(warning_block)
        lines.append('')

    alert_block = format_review_alerts(review_alerts, compact=False)
    if alert_block:
        lines.append(alert_block)
        lines.append('')

    technical_block = format_position_technical_breaks(technical_breaks, compact=False)
    if technical_block:
        lines.append(technical_block)
        lines.append('')

    lines.append(
        f"💰 总资产 ¥{nav['total_value']:,.2f} "
        f"(现金 ¥{nav['cash']:,.2f} + 持仓市值 ¥{nav['market_value']:,.2f})"
    )
    daily_text = '暂停对比' if nav['daily_return'] is None else f"{nav['daily_return']:+.2f}%"
    lines.append(
        f"📈 当日 {daily_text} | "
        f"累计 {nav['cumulative_return']:+.2f}% | "
        f"回撤 {nav['max_drawdown']:+.2f}%"
    )
    lines.append('')

    allocation_section = render_allocation_markdown(allocation, compact=False)
    if allocation_section:
        lines.append(allocation_section)

    lines.append(render_strategy_performance_section(acct['id'], target_date, compact=False))

    entry_snapshot_section = render_entry_strategy_snapshot_section(acct['id'], target_date, compact=False)
    if entry_snapshot_section:
        lines.append(entry_snapshot_section)

    closed_analysis = render_closed_trades_analysis_section(acct['id'], target_date, compact=False)
    if closed_analysis:
        lines.append(closed_analysis)

    signal_perf = render_signal_performance_section(acct['id'], target_date, compact=False)
    if signal_perf:
        lines.append(signal_perf)

    contribution = render_pnl_contribution_section(positions, realized, nav['total_value'], compact=False)
    if contribution:
        lines.append(contribution)

    # 当日交易
    if trades:
        lines.append(f"### 📝 当日交易 {len(trades)} 笔")
        for t in trades:
            arrow = '🟢 买' if t['direction'] == 'BUY' else '🔴 卖'
            amt = t.get('amount') or (t['price'] * t['quantity'])
            fee = (t.get('commission') or 0) + (t.get('tax') or 0)
            reason = t.get('signal_reason') or ''
            line = (
                f"- {arrow} **{t['stock_name']}** ({t['stock_code']}) "
                f"{t['quantity']}股 @¥{t['price']:.2f} = ¥{amt:,.2f} "
                f"(手续费 ¥{fee:.2f})"
            )
            if reason:
                line += f"  _{reason}_"
            lines.append(line)
            # REQ-032: 默认展示摘要，完整信号解释用 details 展开查看。
            lines.extend(render_signal_detail_lines(t.get('signal_detail')))
        lines.append('')

        if realized:
            lines.append(f"### 💵 当日实现盈亏（FIFO 配对）")
            for r in realized:
                emoji = '🟢' if r['pnl'] >= 0 else '🔴'
                lines.append(
                    f"- {emoji} **{r['name']}** ({r['code']}) {r['qty']}股 "
                    f"成本 ¥{r['avg_cost']:.3f} → 卖 ¥{r['sell_price']:.2f} "
                    f"= {r['pnl']:+.2f} ({r['pnl_pct']:+.2f}%)"
                )
            lines.append(f"\n**🎯 当日实现盈亏合计: {realized_pnl:+,.2f}**")
            lines.append('')
    else:
        lines.append('_当日无交易_')
        lines.append('')

    # 当前持仓 + 浮动盈亏
    if positions:
        lines.append(f"### 📦 当前持仓 {len(positions)} 只")
        for p in positions:
            emoji = '🟢' if p['pnl'] >= 0 else '🔴'
            lines.append(
                f"- {emoji} **{p['stock_name']}** ({p['stock_code']}) "
                f"{p['quantity']}股 成本 ¥{p['avg_cost']:.3f} → 现 ¥{p['current_price']:.2f} "
                f"= {p['pnl']:+.2f} ({p['pnl_pct']:+.2f}%) 市值 ¥{p['market_value']:,.0f}"
            )
        lines.append(f"\n**浮动盈亏合计: {floating_pnl:+,.2f}**")
    else:
        lines.append('_当前空仓_')

    lines.append('')

    # nav 趋势（最近 5 天）
    history = fetch_nav_history(acct['id'], target_date, 5)
    if len(history) >= 2:
        lines.append('### 📊 近 5 日总资产')
        for h in reversed(history):
            dr = h.get('daily_return')
            dr_text = '暂停对比' if dr is None else f"{dr:+.2f}%"
            lines.append(
                f"- {h['trade_date']}: ¥{h['total_value']:,.2f} ({dr_text})"
            )
        lines.append('')

    return '\n'.join(lines)


def analyze_intraday_snapshot_coverage(target_date: date, log_path: Path | None = None) -> dict:
    """Audit whether intraday price snapshots cover the full trading day (BUG-005).

    ``portfolio_alert.py`` appends one JSON object per run to
    ``output/intraday_log.jsonl``.  Daily review used to consume the end-state
    account/position tables without checking whether that collector actually ran
    across both trading sessions.  If the scheduler only fires in a narrow
    window (e.g. 13:37 -> 14:55), the review can look complete while missing
    morning and close context.  This helper makes the coverage explicit and
    machine-testable.
    """
    import json

    log_path = log_path or (ROOT / 'output' / 'intraday_log.jsonl')
    sessions = (
        (dtime(9, 30), dtime(11, 30)),
        (dtime(13, 0), dtime(15, 0)),
    )
    result = {
        'date': target_date.isoformat(),
        'log_path': str(log_path),
        'count': 0,
        'first_ts': None,
        'last_ts': None,
        'first_time': None,
        'last_time': None,
        'morning_count': 0,
        'afternoon_count': 0,
        'status': 'missing',
        'warnings': [],
    }

    if not log_path.exists():
        result['warnings'].append('未找到 intraday_log.jsonl，无法验证盘中采样覆盖。')
        return result

    timestamps: list[datetime] = []
    try:
        with log_path.open('r', encoding='utf-8') as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                ts_raw = obj.get('ts') or obj.get('timestamp')
                if not ts_raw or not str(ts_raw).startswith(target_date.isoformat()):
                    continue
                try:
                    ts = datetime.fromisoformat(str(ts_raw))
                except Exception:
                    continue
                timestamps.append(ts)
    except Exception as exc:
        result['warnings'].append(f'读取盘中采样日志失败：{type(exc).__name__}')
        return result

    timestamps.sort()
    result['count'] = len(timestamps)
    if not timestamps:
        result['warnings'].append('当日没有任何盘中价格快照。')
        return result

    first = timestamps[0]
    last = timestamps[-1]
    result.update({
        'first_ts': first.isoformat(),
        'last_ts': last.isoformat(),
        'first_time': first.strftime('%H:%M'),
        'last_time': last.strftime('%H:%M'),
    })

    for ts in timestamps:
        t = ts.time()
        if sessions[0][0] <= t <= sessions[0][1]:
            result['morning_count'] += 1
        elif sessions[1][0] <= t <= sessions[1][1]:
            result['afternoon_count'] += 1

    if result['morning_count'] == 0:
        result['warnings'].append('上午盘缺少采样点（09:30-11:30）。')
    if result['afternoon_count'] == 0:
        result['warnings'].append('下午盘缺少采样点（13:00-15:00）。')
    if first.time() > dtime(9, 45):
        result['warnings'].append(f'首个采样点偏晚：{result["first_time"]}，未覆盖开盘阶段。')
    if last.time() < dtime(14, 55):
        result['warnings'].append(f'最后采样点偏早：{result["last_time"]}，未覆盖收盘阶段。')

    # A full day with a 10-minute Windows task should have roughly 25+ samples;
    # keep the threshold lower to avoid false positives when the task starts late
    # but still covers both sessions.
    if result['count'] < 12:
        result['warnings'].append(f'采样点数量偏少：{result["count"]} 个，建议检查 Windows 计划任务频率。')

    result['status'] = 'ok' if not result['warnings'] else 'partial'
    return result


def render_intraday_snapshot_coverage_section(target_date: date, compact: bool = False) -> str:
    coverage = analyze_intraday_snapshot_coverage(target_date)
    if compact:
        if coverage['status'] == 'ok':
            return ''
        rng = 'N/A' if not coverage.get('first_time') else f"{coverage['first_time']} -> {coverage['last_time']}"
        return f"⚠️ 盘中采样覆盖不完整：{coverage['count']} 点，范围 {rng}；请检查 QuantLearn_PortfolioAlert 计划任务。"

    lines = ['## 🧭 盘中采样覆盖审计', '']
    rng = 'N/A' if not coverage.get('first_time') else f"{coverage['first_time']} -> {coverage['last_time']}"
    status_text = '✅ 完整' if coverage['status'] == 'ok' else '⚠️ 不完整'
    lines.append(f"- 状态：**{status_text}**")
    lines.append(f"- 数据点：{coverage['count']} 个；收集范围：{rng}")
    lines.append(f"- 上午/下午采样：{coverage['morning_count']} / {coverage['afternoon_count']}")
    if coverage['warnings']:
        lines.append('- 诊断：')
        for w in coverage['warnings']:
            lines.append(f"  - {w}")
        lines.append('- 建议：确认 `QuantLearn_PortfolioAlert`/`portfolio_alert_runner.bat` 在交易日 09:30-11:30、13:00-15:00 按 5-10 分钟频率运行；复盘应在 15:05 后生成。')
    lines.append('')
    return '\n'.join(lines)


def generate_full_md(target_date: date) -> str:
    sentiment = fetch_market_sentiment(target_date)
    parts = [f"# 📊 {target_date.year}/{target_date.month}/{target_date.day} 日复盘\n"]
    parts.append(render_market_sentiment_section(sentiment, compact=False))
    parts.append(render_intraday_snapshot_coverage_section(target_date, compact=False))
    parts.append('---\n')
    for acct in ACCOUNTS:
        parts.append(render_account_section(acct, target_date, sentiment))
        parts.append('---\n')
    parts.append(render_execution_consistency_section(target_date, compact=False))
    parts.append('---\n')
    parts.append(f"_生成时间: {datetime.now():%Y-%m-%d %H:%M:%S}_\n")
    return '\n'.join(parts)


def generate_wecom_summary(target_date: date) -> str:
    """精简版给企微（只放真实账户 + 学习账户的当日核心数据）"""
    sentiment = fetch_market_sentiment(target_date)
    lines = [f"# 📊 {target_date.year}/{target_date.month}/{target_date.day} 日复盘\n"]
    lines.append(render_market_sentiment_section(sentiment, compact=True))
    coverage_warning = render_intraday_snapshot_coverage_section(target_date, compact=True)
    if coverage_warning:
        lines.append(coverage_warning)
    lines.append('')

    for acct in ACCOUNTS:
        account = fetch_account(acct['id'])
        if not account:
            continue
        positions = fetch_positions(acct['id'])
        try:
            from sim.config import get_account_config
            config_initial = get_account_config(acct['id'])['initial_cash']
        except Exception:
            config_initial = account.get('initial_cash', 100000.0)
        basis_warnings = detect_account_basis_changes(account, positions, target_date, config_initial)
        trades = fetch_trades(acct['id'], target_date)
        realized = compute_realized_pnl(acct['id'], target_date)
        nav_history = fetch_nav_history(acct['id'], target_date, 1)
        nav = nav_history[0] if nav_history else None
        review_alerts = detect_trade_anomaly_alerts(account, positions, trades, realized, nav, target_date)
        technical_breaks = detect_position_technical_breaks(positions, target_date)
        allocation = summarize_allocation(account, positions, fetch_recent_entry_trades(acct['id']), sentiment, load_config())

        title_prefix = '⚠️ ' if (basis_warnings or review_alerts or has_technical_break_issue(technical_breaks)) else ''
        lines.append(f"## {title_prefix}{acct['icon']} {acct['name']}")
        if nav:
            dr = nav.get('daily_return')
            dr_text = '暂停对比' if dr is None else f"{dr:+.2f}%"
            lines.append(
                f"💰 ¥{nav['total_value']:,.0f} "
                f"({dr_text} / 累计 {nav['cumulative_return']:+.2f}%)"
            )
            lines.append(render_strategy_performance_section(acct['id'], target_date, compact=True))
            closed_summary = render_closed_trades_analysis_section(acct['id'], target_date, compact=True)
            if closed_summary:
                lines.append(closed_summary)
            allocation_summary = render_allocation_markdown(allocation, compact=True)
            if allocation_summary:
                lines.append(allocation_summary)
            signal_summary = render_signal_performance_section(acct['id'], target_date, compact=True)
            if signal_summary:
                lines.append(signal_summary)
        if basis_warnings:
            lines.append('⚠️ 账户资金口径变更：已暂停跨日收益率对比')
        alert_block = format_review_alerts(review_alerts, compact=True)
        if alert_block:
            lines.append(alert_block)
        technical_block = format_position_technical_breaks(technical_breaks, compact=True)
        if technical_block:
            lines.append(technical_block)
        if trades:
            buy_n = sum(1 for t in trades if t['direction'] == 'BUY')
            sell_n = len(trades) - buy_n
            realized_pnl = sum(r['pnl'] for r in realized)
            lines.append(f"📝 交易 {len(trades)} 笔（买 {buy_n} / 卖 {sell_n}）")
            for t in trades[:5]:
                arrow = '🟢' if t['direction'] == 'BUY' else '🔴'
                action = '买' if t['direction'] == 'BUY' else '卖'
                lines.append(
                    f"- {arrow} {action} {t['stock_name']} {t['quantity']}股 @¥{t['price']:.2f}"
                )
            if realized:
                emoji = '🎉' if realized_pnl >= 0 else '😢'
                lines.append(f"💵 实现盈亏 **{realized_pnl:+,.2f}** {emoji}")
        else:
            lines.append('_当日无交易_')

        if positions:
            float_pnl = sum(p['pnl'] for p in positions)
            lines.append(f"📦 持仓 {len(positions)} 只 浮动 {float_pnl:+,.2f}")
            for p in positions[:3]:
                emoji = '🟢' if p['pnl'] >= 0 else '🔴'
                lines.append(
                    f"  {emoji} {p['stock_name']} {p['quantity']}股 → "
                    f"{p['pnl_pct']:+.2f}% ({p['pnl']:+.0f})"
                )

        contribution = render_pnl_contribution_section(positions, realized, nav['total_value'] if nav else None, compact=True)
        if contribution:
            lines.append(contribution)

        lines.append('')

    lines.append(render_execution_consistency_section(target_date, compact=True))
    lines.append('')

    return '\n'.join(lines)


# =====================================
# 5. 推送
# =====================================
def push_webhook(content: str) -> bool:
    cfg = load_config()
    webhook = (cfg.get('notifier') or {}).get('wecom_webhook', '')
    if not webhook:
        logger.warning('未配置 wecom_webhook，跳过推送')
        return False
    try:
        resp = requests.post(webhook, json={
            'msgtype': 'markdown',
            'markdown': {'content': content}
        }, timeout=8)
        ok = resp.json().get('errcode') == 0
        logger.info(f'推送 {"成功" if ok else "失败"}: {resp.text[:120]}')
        return ok
    except Exception as e:
        logger.error(f'推送异常: {e}')
        return False


# =====================================
# 6. 主流程
# =====================================
def get_target_date() -> date:
    """命令行 arg 或 今日"""
    if len(sys.argv) > 1:
        return date.fromisoformat(sys.argv[1])
    return date.today()


def main():
    target_date = get_target_date()
    logger.info(f'=== 开始复盘 {target_date} ===')

    full_md = generate_full_md(target_date)
    out_dir = ROOT / 'output' / 'reviews'
    out_dir.mkdir(parents=True, exist_ok=True)
    md_file = out_dir / f"{target_date.isoformat()}.md"
    md_file.write_text(full_md, encoding='utf-8')
    logger.info(f'✓ 完整版已存: {md_file}')

    summary = generate_wecom_summary(target_date)
    sum_file = out_dir / f"{target_date.isoformat()}_summary.md"
    sum_file.write_text(summary, encoding='utf-8')
    logger.info(f'✓ 精简版已存: {sum_file}')

    # 仅在 push=1 / push=true 时推送（默认不推，需要时显式）
    push_flag = os.environ.get('PUSH', '').lower() in ('1', 'true', 'yes')
    if push_flag:
        push_webhook(summary)
    else:
        logger.info('未推送（设 PUSH=1 启用），可执行 `python scripts/daily_review.py %s` 重跑' % target_date)

    print('\n' + '=' * 70)
    try:
        print(summary)
    except UnicodeEncodeError:
        # Windows GBK 控制台处理不了 emoji，转 ascii 安全输出
        sys.stdout.buffer.write((summary + '\n').encode('utf-8', errors='replace'))
    print('=' * 70)


if __name__ == '__main__':
    main()
