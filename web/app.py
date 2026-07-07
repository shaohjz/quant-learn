"""
持仓 Web 仪表盘 v2 — 参考券商APP设计
端口: 8080
"""
import sys, json, sqlite3, re
from pathlib import Path
from datetime import datetime, date, timedelta
from flask import Flask, jsonify, request, send_from_directory, render_template_string
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.closed_trades import analyze_closed_trades
from sim.asset_allocation import summarize_allocation
from sim.market_sentiment import fetch_market_sentiment

app = Flask(__name__)
DB_PATH = ROOT / "data" / "sim_live_mirror.db"

# ====================================================================
#  行情
# ====================================================================
def get_sina_prices(codes):
    if not codes:
        return {}
    import urllib.request
    sina_codes = []
    for c in codes:
        prefix = 'sh' if c.startswith(('60', '68', '11', '5')) else 'sz'
        sina_codes.append(prefix + c)
    url = 'https://hq.sinajs.cn/list=' + ','.join(sina_codes)
    headers = {'Referer': 'https://finance.sina.com.cn'}
    try:
        req = urllib.request.Request(url, headers=headers)
        r = urllib.request.urlopen(req, timeout=10)
        text = r.read().decode('gbk')
    except:
        return {}
    prices = {}
    for line in text.strip().split('\n'):
        m = re.search(r'hq_str_(s[hz])(\d+)="(.+?)"', line)
        if m:
            parts = m.group(3).split(',')
            if len(parts) >= 10 and parts[3]:
                code = m.group(2)
                try:
                    raw_price = float(parts[3] or 0)
                    yclose = float(parts[2] or 0)
                    open_price = float(parts[1] or 0)
                    # 早盘/非交易时段新浪可能返回现价=0，不能把持仓市值打成 0。
                    # 优先用昨收兜底；如果昨收也缺失，再由调用方使用数据库当前价/成本价兜底。
                    price = raw_price if raw_price > 0 else yclose
                    pct = round((price - yclose) / yclose * 100, 2) if yclose > 0 and raw_price > 0 else 0
                    prices[code] = {
                        'name': parts[0],
                        'price': price,
                        'yclose': yclose,
                        'open': open_price,
                        'high': float(parts[4] or 0),
                        'low': float(parts[5] or 0),
                        'volume': float(parts[8] or 0),
                        'amount': float(parts[9] or 0),
                        'pct': pct,
                    }
                except (ValueError, IndexError):
                    pass
    return prices

# ====================================================================
#  DB
# ====================================================================
def sim_db_path():
    """Return simulation DB path; overridable in tests via app.config['SIM_DB_PATH']."""
    return Path(app.config.get("SIM_DB_PATH", DB_PATH))


def config_path():
    """Return main config path; overridable in tests via app.config['CONFIG_PATH']."""
    return Path(app.config.get("CONFIG_PATH", ROOT / "config.yaml"))


def _sim_conn():
    conn = sqlite3.connect(str(sim_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


def query_db(sql, params=()):
    conn = _sim_conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ====================================================================
#  API: 模拟盘
# ====================================================================
@app.route('/api/portfolio')
def api_portfolio():
    account_id = int(request.args.get('account_id', 1))
    positions = query_db("SELECT * FROM sim_positions WHERE account_id=? AND quantity > 0", (account_id,))
    acc_rows = query_db("SELECT * FROM sim_account WHERE id=?", (account_id,))
    acc = acc_rows[0] if acc_rows else {'cash': 0, 'initial_cash': 0, 'total_value': 0}
    cfg = yaml.safe_load(config_path().read_text(encoding='utf-8')) or {}

    # 根据 account_id 读取对应配置
    acct_key = 'learn' if account_id == 1 else 'real'
    initial_cash = float(
        cfg.get('accounts', {}).get(acct_key, {}).get(
            'initial_cash', acc.get('initial_cash') or 200000
        )
    )
    account_name = cfg.get('accounts', {}).get(acct_key, {}).get('account_name', acc.get('account_name', ''))

    codes = [p['stock_code'] for p in positions]
    rt = get_sina_prices(codes)

    result = []
    total_mv = 0
    total_pnl = 0
    for p in positions:
        code = p['stock_code']
        rt_price = rt.get(code, {}).get('price', 0) or 0
        cur = rt_price if rt_price > 0 else (p.get('current_price') or p.get('avg_cost', 0) or 0)
        pct_today = rt.get(code, {}).get('pct', 0)
        qty = p['quantity']
        cost = p['avg_cost']
        mv = cur * qty
        pnl = (cur - cost) * qty
        pnl_pct = (cur - cost) / cost * 100 if cost > 0 else 0
        total_mv += mv
        total_pnl += pnl

        # 查交易理由
        trades = query_db(
            "SELECT signal_reason, trade_date FROM sim_trades WHERE stock_code=? AND direction='BUY' ORDER BY created_at LIMIT 1",
            (code,)
        )
        reason = trades[0]['signal_reason'] if trades and trades[0].get('signal_reason') else '阈值触发自动买入'

        result.append({
            'code': code,
            'name': p.get('stock_name', rt.get(code, {}).get('name', '')),
            'quantity': qty,
            'avg_cost': round(cost, 3),
            'current_price': round(cur, 2),
            'pct_today': round(pct_today, 2),
            'market_value': round(mv, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
            'buy_reason': reason,
            'high': rt.get(code, {}).get('high', 0),
            'low': rt.get(code, {}).get('low', 0),
            'amount': rt.get(code, {}).get('amount', 0),
        })

    # [REQ-005] 正确计算总资产：现金 + 持仓市值
    cash = float(acc.get('cash', 0) or 0)
    total_asset = round(cash + total_mv, 2)
    total_mv = round(total_mv, 2)

    # [REQ-005] 数据校验：对比 DB total_value 与计算结果
    # 说明：total_asset 使用实时行情价计算，DB total_value 是上次 daily_settle 的收盘值
    # 两者在交易时段会有差异，仅当差异 >5% 时告警
    db_total_value = float(acc.get('total_value', 0) or 0)
    value_mismatch = False
    mismatch_msg = ''
    if db_total_value > 0 and total_asset > 0:
        mismatch_ratio = abs(db_total_value - total_asset) / max(db_total_value, total_asset)
        if mismatch_ratio > 0.05:  # 差异超过 5%
            value_mismatch = True
            mismatch_msg = f"总资产偏差 {mismatch_ratio*100:.1f}%: DB({db_total_value:,.2f}) vs 实时({total_asset:,.2f})"

    # [REQ-005] 数据校验：总资产 vs 现金+持仓市值 核对
    asset_check = {
        'cash': round(cash, 2),
        'total_market_value': total_mv,
        'total_asset_computed': total_asset,
        'db_total_value': round(db_total_value, 2),
        'value_mismatch': value_mismatch,
        'mismatch_msg': mismatch_msg,
    }

    total_return_pct = round((total_asset - initial_cash) / initial_cash * 100, 2) if initial_cash > 0 else 0
    position_pct = round(total_mv / total_asset * 100, 1) if total_asset > 0 else 0

    return jsonify({
        'account': {
            'account_id': account_id,
            'account_name': account_name,
            'cash': round(cash, 2),
            'initial_cash': round(initial_cash, 2),
            'total_asset': total_asset,
            'total_return_pct': total_return_pct,
            'position_pct': position_pct,
            'value_mismatch': value_mismatch,
            'mismatch_msg': mismatch_msg,
        },
        'positions': result,
        'total_market_value': total_mv,
        'total_pnl': round(total_pnl, 2),
        'asset_check': asset_check,
        'updated_at': datetime.now().strftime('%H:%M:%S'),
    })

# ====================================================================
#  API: 观察列表
# ====================================================================
@app.route('/api/watchlist')
def api_watchlist():
    cfg = yaml.safe_load(config_path().read_text(encoding='utf-8'))
    wl = cfg.get('watchlist', {})
    um = wl.get('user_manual', {}) if isinstance(wl, dict) else {}
    
    auto_path = ROOT / "config_auto.yaml"
    auto_cfg = yaml.safe_load(auto_path.read_text(encoding='utf-8')) if auto_path.exists() else {}
    ad = auto_cfg.get('auto_discovered', {}) if auto_cfg else {}
    
    # 合并所有观察股
    all_codes = list(set(list(um.keys()) + list(ad.keys())))
    rt = get_sina_prices(all_codes)
    
    result = []
    for code, info in um.items():
        if not info.get('enabled', True):
            continue
        price = rt.get(code, {}).get('price', 0)
        pct_today = rt.get(code, {}).get('pct', 0)
        
        # 计算从加入以来的涨跌
        added_at = str(info.get('added_at', ''))
        # 用加入时的实际股价作为参考价
        ref_price = info.get('added_price', 0)
        if not ref_price:
            # fallback: 如果没有 added_price，用 buy_zone trigger
            rules = info.get('rules', {})
            if isinstance(rules, dict):
                bz = rules.get('buy_zone', {})
                if isinstance(bz, dict):
                    ref_price = bz.get('trigger', 0)
        since_pct = round((price - ref_price) / ref_price * 100, 1) if ref_price > 0 and price > 0 else None
        
        rules = info.get('rules', {})
        result.append({
            'code': code,
            'name': info.get('name', rt.get(code, {}).get('name', '')),
            'source': info.get('source', '手动添加'),
            'added_at': added_at,
            'added_reason': info.get('added_reason', ''),
            'added_price': ref_price,
            'tags': info.get('tags', []),
            'price': round(price, 2),
            'pct_today': round(pct_today, 2),
            'since_pct': since_pct,
            'category': 'user_manual',
            'buy_zone': rules.get('buy_zone', {}).get('trigger', 0) if isinstance(rules, dict) else 0,
            'buy_strong': rules.get('buy_strong', {}).get('trigger', 0) if isinstance(rules, dict) else 0,
        })
    
    for code, info in ad.items():
        if not info.get('enabled', True):
            continue
        price = rt.get(code, {}).get('price', 0)
        pct_today = rt.get(code, {}).get('pct', 0)
        auto_ref = info.get('added_price', info.get('discovery_price', 0))
        auto_since = round((price - auto_ref) / auto_ref * 100, 1) if auto_ref > 0 and price > 0 else None
        result.append({
            'code': code,
            'name': info.get('name', rt.get(code, {}).get('name', '')),
            'source': info.get('source', 'intraday_scanner'),
            'added_at': str(info.get('added_at', '')),
            'added_reason': info.get('added_reason', ''),
            'added_price': auto_ref,
            'tags': [],
            'price': round(price, 2),
            'pct_today': round(pct_today, 2),
            'since_pct': auto_since,
            'category': 'auto_discovered',
            'buy_zone': info.get('buy_zone', 0),
            'buy_strong': info.get('buy_strong', 0),
        })
    
    return jsonify({'watchlist': result, 'updated_at': datetime.now().strftime('%H:%M:%S')})

@app.route('/api/selection_logic')
def api_selection_logic():
    """获取选股逻辑说明"""
    logic_path = ROOT / 'docs' / 'selection_logic.yaml'
    if logic_path.exists():
        data = yaml.safe_load(logic_path.read_text(encoding='utf-8'))
        return jsonify(data.get('stock_selection_logic', {}))
    return jsonify({})


def _pct(v):
    try:
        return round(float(v) * 100, 1)
    except Exception:
        return 0


def _rule_text(rule_key, rule):
    """Format a YAML rule into PM/FA-friendly text."""
    if not isinstance(rule, dict):
        return str(rule)
    label_map = {
        'buy_zone': '买入观察', 'buy_strong': '强买区', 'stop_loss_tight': '接近止损',
        'stop_loss_soft': '软止损', 'stop_loss': '硬止损', 'hard_stop': '硬止损',
        'half_out': '减半卖出', 'take_profit_half': '止盈减仓', 'take_profit': '止盈',
        'trend_break': '趋势破位',
    }
    label = label_map.get(rule_key, rule_key)
    trigger = rule.get('trigger')
    direction = '跌破/低于' if rule.get('dir') == 'below' else ('突破/高于' if rule.get('dir') == 'above' else rule.get('dir', ''))
    msg = rule.get('msg', '')
    head = f"{label}: {direction} {trigger}" if trigger not in (None, '') else label
    return f"{head}｜{msg}" if msg else head


def _collect_watch_rules(watchlist, auto_cfg):
    rows = []
    if isinstance(watchlist, dict):
        for category in ('user_manual', 'auto_discovered'):
            for code, info in (watchlist.get(category, {}) or {}).items():
                if not isinstance(info, dict) or not info.get('enabled', True):
                    continue
                rules = info.get('rules', {}) if isinstance(info.get('rules', {}), dict) else {}
                buy_rules = [_rule_text(k, v) for k, v in rules.items() if str(k).startswith('buy')]
                rows.append({
                    'code': str(code),
                    'name': info.get('name', ''),
                    'category': category,
                    'source': info.get('source', '观察池'),
                    'trigger_rules': buy_rules,
                    'trend_gate': (info.get('trend_filter') or {}).get('gate', ''),
                    'status': (info.get('trend_filter') or {}).get('status', ''),
                    'added_reason': info.get('added_reason', ''),
                })
    for code, info in ((auto_cfg or {}).get('auto_discovered', {}) or {}).items():
        if not isinstance(info, dict) or not info.get('enabled', True):
            continue
        rows.append({
            'code': str(code),
            'name': info.get('name', ''),
            'category': 'auto_discovered',
            'source': info.get('source', 'intraday_scanner'),
            'trigger_rules': [r for r in [
                f"买入观察: 跌破/低于 {info.get('buy_zone')}" if info.get('buy_zone') else '',
                f"强买区: 跌破/低于 {info.get('buy_strong')}" if info.get('buy_strong') else '',
            ] if r],
            'trend_gate': '',
            'status': '',
            'added_reason': info.get('added_reason', ''),
        })
    return rows


@app.route('/api/strategy_control')
def api_strategy_control():
    """策略控制大盘：规则、仓位限制、现金水位、最近命中/执行结果。"""
    account_id = int(request.args.get('account_id', 1))
    cfg = yaml.safe_load(config_path().read_text(encoding='utf-8')) or {}
    risk = cfg.get('risk', {}) or {}
    accounts = cfg.get('accounts', {}) or {}
    # 根据 account_id 选择对应配置
    acct_key = 'learn' if account_id == 1 else 'real'
    acct_cfg = accounts.get(acct_key, {}) or {}

    account = query_db("SELECT * FROM sim_account WHERE id=?", (account_id,))
    account = account[0] if account else {'cash': 0, 'initial_cash': acct_cfg.get('initial_cash', cfg.get('account', {}).get('initial_cash', 0))}
    positions = query_db("SELECT stock_code, stock_name, quantity, avg_cost, current_price, market_value, pnl, pnl_pct FROM sim_positions WHERE account_id=? AND quantity > 0", (account_id,))
    total_market_value = sum(float(p.get('market_value') or 0) for p in positions)
    cash = float(account.get('cash') or 0)
    total_asset = cash + total_market_value
    today = date.today().isoformat()
    today_new_positions = query_db(
        "SELECT COUNT(DISTINCT stock_code) AS cnt FROM sim_trades WHERE account_id=? AND direction='BUY' AND trade_date=?",
        (account_id, today),
    )[0]['cnt']
    today_buy_amount = query_db(
        "SELECT COALESCE(SUM(amount), 0) AS amt FROM sim_trades WHERE account_id=? AND direction='BUY' AND trade_date=?",
        (account_id, today),
    )[0]['amt']

    holding_rules = []  # 实盘已移除，holding_rules 从 config.yaml watchlist 的 sell 规则提取
    initial_cash = float(acct_cfg.get('initial_cash', account.get('initial_cash', 100000.0)))

    auto_path = ROOT / "config_auto.yaml"
    auto_cfg = yaml.safe_load(auto_path.read_text(encoding='utf-8')) if auto_path.exists() else {}
    watch_rows = _collect_watch_rules((cfg.get('watchlist') or {}), auto_cfg)

    recent_trades = query_db(
        "SELECT trade_date, trade_time, stock_code, stock_name, direction, quantity, price, amount, signal_reason, trade_context, signal_detail, created_at "
        "FROM sim_trades WHERE account_id=? ORDER BY created_at DESC LIMIT 12",
        (account_id,),
    )
    recent_orders = query_db(
        "SELECT order_time, order_id, broker_order_id, broker, stock_code, stock_name, direction, quantity, traded, price, status, strategy_name, signal_reason, created_at "
        "FROM sim_orders WHERE account_id=? ORDER BY COALESCE(order_time, created_at) DESC LIMIT 12",
        (account_id,),
    )
    qmt_orders = query_db(
        "SELECT order_time, order_id, broker_order_id, broker, stock_code, stock_name, direction, quantity, traded, price, status, strategy_name, signal_reason, created_at "
        "FROM sim_orders WHERE account_id=? AND broker LIKE 'qmt%' ORDER BY COALESCE(order_time, created_at) DESC LIMIT 20",
        (account_id,),
    )
    qmt_fills = query_db(
        "SELECT trade_time, order_id, broker_trade_id, broker, stock_code, stock_name, direction, trade_volume, trade_price, trade_amount, strategy_name, created_at "
        "FROM sim_fills WHERE account_id=? AND broker LIKE 'qmt%' ORDER BY COALESCE(trade_time, created_at) DESC LIMIT 20",
        (account_id,),
    )
    for row in recent_trades:
        for key in ('trade_context', 'signal_detail'):
            if row.get(key):
                try:
                    row[key] = json.loads(row[key])
                except Exception:
                    pass

    return jsonify({
        'updated_at': datetime.now().strftime('%H:%M:%S'),
        'buy_rules': {
            'summary': '观察池触发 + 趋势过滤 + 风控校验后建仓；自动买入以 sim/learn 账户配置为准。',
            'watchlist_count': len(watch_rows),
            'sample_rules': watch_rows[:30],
        },
        'sell_rules': {
            'summary': '持仓规则优先使用逐票止损/止盈/减仓线；全局兜底使用 risk.stop_loss_pct / risk.take_profit_pct。',
            'global_stop_loss_pct': _pct(risk.get('stop_loss_pct', -0.08)),
            'global_take_profit_pct': _pct(risk.get('take_profit_pct', 0.15)),
            'holding_rules': holding_rules,
        },
        'position_controls': {
            'auto_trade': bool(acct_cfg.get('auto_trade', False)),
            'max_position_pct': _pct(risk.get('max_position_pct', 0)),
            'max_total_positions': int(risk.get('max_total_positions', 0) or 0),
            'max_daily_new_positions': int(risk.get('max_daily_new_positions', 0) or 0),
            'max_daily_trades': int(risk.get('max_daily_trades', 0) or 0),
            'max_daily_build_amount_pct': _pct(risk.get('max_daily_build_amount_pct', 0)),
            'max_total_value': float(acct_cfg.get('max_total_value', 0) or 0),
            'current_positions': len(positions),
            'today_new_positions': int(today_new_positions or 0),
            'today_buy_amount': round(float(today_buy_amount or 0), 2),
        },
        'cash_level': {
            'cash': round(cash, 2),
            'total_market_value': round(total_market_value, 2),
            'total_asset': round(total_asset, 2),
            'cash_pct': round(cash / total_asset * 100, 1) if total_asset > 0 else 0,
            'position_pct': round(total_market_value / total_asset * 100, 1) if total_asset > 0 else 0,
        },
        'recent_hits': {
            'trades': recent_trades,
            'orders': recent_orders,
        },
        'qmt_flow': {
            'orders': qmt_orders,
            'fills': qmt_fills,
        },
    })


@app.route('/api/asset_allocation')
def api_asset_allocation():
    """REQ-031: broad asset allocation and dynamic strategy exposure dashboard."""
    account_id = int(request.args.get('account_id', 1))
    account_rows = query_db("SELECT * FROM sim_account WHERE id=?", (account_id,))
    account = account_rows[0] if account_rows else {'id': account_id, 'cash': 0, 'initial_cash': 0}
    positions = query_db("SELECT * FROM sim_positions WHERE account_id=? AND quantity > 0 ORDER BY market_value DESC", (account_id,))
    trades = query_db(
        "SELECT * FROM sim_trades WHERE account_id=? ORDER BY COALESCE(created_at, trade_date) DESC, id DESC LIMIT 300",
        (account_id,),
    )
    try:
        market = fetch_market_sentiment(date.today())
    except Exception:
        market = None
    cfg = yaml.safe_load(config_path().read_text(encoding='utf-8')) or {}
    return jsonify({
        'updated_at': datetime.now().strftime('%H:%M:%S'),
        'allocation': summarize_allocation(account, positions, trades, market, cfg),
    })


@app.route('/api/qmt_order_flow')
def api_qmt_order_flow():
    """QMT 委托/成交状态流：用于实盘与模拟盘明细对比和回放。"""
    account_id = int(request.args.get('account_id', 1))
    limit = int(request.args.get('limit', 50))
    orders = query_db(
        "SELECT order_time, order_id, broker_order_id, broker, stock_code, stock_name, direction, "
        "quantity, traded, price, status, strategy_name, signal_reason, created_at "
        "FROM sim_orders WHERE account_id=? AND broker LIKE 'qmt%' "
        "ORDER BY COALESCE(order_time, created_at) DESC LIMIT ?",
        (account_id, limit),
    )
    fills = query_db(
        "SELECT trade_time, order_id, broker_trade_id, broker, stock_code, stock_name, direction, "
        "trade_volume, trade_price, trade_amount, commission, tax, strategy_name, created_at "
        "FROM sim_fills WHERE account_id=? AND broker LIKE 'qmt%' "
        "ORDER BY COALESCE(trade_time, created_at) DESC LIMIT ?",
        (account_id, limit),
    )
    events = []
    for o in orders:
        events.append({
            'type': 'order',
            'time': o.get('order_time') or o.get('created_at'),
            **o,
        })
    for f in fills:
        events.append({
            'type': 'fill',
            'time': f.get('trade_time') or f.get('created_at'),
            **f,
        })
    events.sort(key=lambda x: x.get('time') or '', reverse=True)
    return jsonify({'orders': orders, 'fills': fills, 'events': events[:limit], 'total': len(events)})

# ====================================================================
#  API: 全部交易历史
# ====================================================================
@app.route('/api/trades')
def api_trades():
    """获取交易记录，支持按 account_id 过滤"""
    from flask import request as _req
    account_id = int(_req.args.get('account_id', 1))
    limit = int(_req.args.get('limit', 50))
    trades = query_db(
        "SELECT id, trade_date, trade_time, account_id, stock_code, direction, "
        "quantity, price, amount, signal_reason, trade_context, created_at "
        "FROM sim_trades WHERE account_id=? ORDER BY created_at DESC LIMIT ?",
        (account_id, limit)
    )
    import json as _json
    for t in trades:
        if t.get('trade_context'):
            try:
                t['trade_context'] = _json.loads(t['trade_context'])
            except:
                pass
    return jsonify({'trades': trades, 'total': len(trades)})


# ====================================================================
#  API: 单股交易历史
# ====================================================================
@app.route('/api/stock_trades/<code>')
def api_stock_trades(code):
    trades = query_db(
        "SELECT trade_date, trade_time, direction, quantity, price, amount, signal_reason, trade_context FROM sim_trades WHERE stock_code=? ORDER BY created_at DESC LIMIT 20",
        (code,)
    )
    # 解析 trade_context JSON
    import json as _json
    for t in trades:
        if t.get('trade_context'):
            try:
                t['trade_context'] = _json.loads(t['trade_context'])
            except:
                pass
    return jsonify({'trades': trades})

@app.route('/api/closed_trades')
def api_closed_trades():
    """REQ-023: 已平仓历史交易盈亏分析，支持 account_id/as_of/limit。"""
    account_id = int(request.args.get('account_id', 1))
    limit = int(request.args.get('limit', 50))
    as_of_raw = request.args.get('as_of') or ''
    as_of = None
    if as_of_raw:
        try:
            as_of = date.fromisoformat(as_of_raw[:10])
        except ValueError:
            return jsonify({'error': 'invalid as_of, expected YYYY-MM-DD'}), 400
    data = analyze_closed_trades(account_id, as_of, conn_factory=_sim_conn, limit=limit)
    return jsonify(data)


@app.route('/api/push_history')
def api_push_history():
    """获取推送历史"""
    limit = int(request.args.get('limit', 20)) if 'request' in dir() else 20
    from flask import request as _req
    limit = int(_req.args.get('limit', 20))
    phase = _req.args.get('phase', '')
    if phase:
        rows = query_db(
            "SELECT id, push_type, phase, content, created_at FROM push_history WHERE phase=? ORDER BY created_at DESC LIMIT ?",
            (phase, limit)
        )
    else:
        rows = query_db(
            "SELECT id, push_type, phase, content, created_at FROM push_history ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
    return jsonify({'history': rows})

@app.route('/api/position_notes/<code>')
def api_position_notes(code):
    """获取持仓笔记/理由"""
    notes = query_db(
        "SELECT note_type, content, created_at FROM position_notes WHERE stock_code=? ORDER BY created_at DESC",
        (code,)
    )
    return jsonify({'notes': notes})

# ====================================================================
#  API: 账户统计
# ====================================================================
@app.route('/api/stats')
def api_stats():
    account_id = int(request.args.get('account_id', 1))
    # 近7天交易统计
    since_week = (date.today() - timedelta(days=7)).isoformat()
    week_trades = query_db(
        "SELECT trade_date, direction, amount FROM sim_trades WHERE account_id=? AND trade_date >= ?",
        (account_id, since_week,)
    )
    week_buy_count = sum(1 for t in week_trades if t['direction'] == 'BUY')
    week_sell_count = sum(1 for t in week_trades if t['direction'] == 'SELL')
    week_buy_amount = sum(t.get('amount', 0) or 0 for t in week_trades if t['direction'] == 'BUY')
    week_sell_amount = sum(t.get('amount', 0) or 0 for t in week_trades if t['direction'] == 'SELL')
    
    # 本月交易统计
    since_month = date.today().replace(day=1).isoformat()
    month_trades = query_db(
        "SELECT trade_date, direction, amount FROM sim_trades WHERE account_id=? AND trade_date >= ?",
        (account_id, since_month,)
    )
    month_buy_count = sum(1 for t in month_trades if t['direction'] == 'BUY')
    month_sell_count = sum(1 for t in month_trades if t['direction'] == 'SELL')
    month_buy_amount = sum(t.get('amount', 0) or 0 for t in month_trades if t['direction'] == 'BUY')
    month_sell_amount = sum(t.get('amount', 0) or 0 for t in month_trades if t['direction'] == 'SELL')
    
    # 总交易统计
    all_trades = query_db("SELECT id, trade_date, direction, price, stock_code FROM sim_trades WHERE account_id=?", (account_id,))
    total_trades = len(all_trades)
    
    closed_data = analyze_closed_trades(account_id, conn_factory=_sim_conn, limit=20)
    closed_summary = closed_data['summary']
    max_profit = closed_summary.get('max_profit_trade') or {}
    max_loss = closed_summary.get('max_loss_trade') or {}

    def _trade_card(row):
        return {
            'code': row.get('stock_code', ''),
            'name': row.get('stock_name', ''),
            'pnl': round(float(row.get('pnl') or 0), 2),
            'pnl_pct': round(float(row.get('pnl_pct') or 0), 2),
            'date': row.get('close_date', ''),
        }
    
    return jsonify({
        'total_trades': total_trades,
        'win_rate': round(closed_summary['win_rate'], 1),
        'avg_hold_days': round(closed_summary['avg_holding_days'] or 0, 1),
        'max_profit_trade': _trade_card(max_profit),
        'max_loss_trade': _trade_card(max_loss),
        'closed_trades': {
            'closed_count': closed_summary['closed_count'],
            'win_count': closed_summary['win_count'],
            'loss_count': closed_summary['loss_count'],
            'net_pnl': round(closed_summary['net_pnl'], 2),
            'gross_profit': round(closed_summary['gross_profit'], 2),
            'gross_loss': round(closed_summary['gross_loss'], 2),
            'avg_win': round(closed_summary['avg_win'], 2),
            'avg_loss': round(closed_summary['avg_loss'], 2),
            'payoff_ratio': None if closed_summary['payoff_ratio'] is None else round(closed_summary['payoff_ratio'], 2),
            'profit_factor': None if closed_summary['profit_factor'] is None or closed_summary['profit_factor'] == float('inf') else round(closed_summary['profit_factor'], 2),
            'by_symbol': closed_summary['by_symbol'][:8],
            'recent': closed_data['closed_trades'][:8],
        },
        'week_trades': {
            'buy_count': week_buy_count,
            'sell_count': week_sell_count,
            'buy_amount': round(week_buy_amount, 0),
            'sell_amount': round(week_sell_amount, 0),
        },
        'month_trades': {
            'buy_count': month_buy_count,
            'sell_count': month_sell_count,
            'buy_amount': round(month_buy_amount, 0),
            'sell_amount': round(month_sell_amount, 0),
        },
    })

# ====================================================================
#  API: 收益率曲线
# ====================================================================
@app.route('/api/equity_curve')
def api_equity_curve():
    """获取近30天收益率曲线数据，支持 account_id 参数"""
    account_id = int(request.args.get('account_id', 1))
    since_date = (date.today() - timedelta(days=30)).isoformat()
    snapshots = query_db(
        "SELECT trade_date, total_value, cumulative_return FROM sim_daily_nav "
        "WHERE account_id=? AND trade_date >= ? ORDER BY trade_date",
        (account_id, since_date)
    )
    
    if not snapshots:
        return jsonify({'dates': [], 'total_asset': [], 'benchmark': [], 'returns': []})
    
    # 获取 initial_cash 用于计算收益率
    cfg = yaml.safe_load(config_path().read_text(encoding='utf-8')) or {}
    acct_key = 'learn' if account_id == 1 else 'real'
    initial_cash = float(
        cfg.get('accounts', {}).get(acct_key, {}).get('initial_cash', 100000.0)
    )
    
    dates = [s['trade_date'] for s in snapshots]
    total_assets = [round(float(s['total_value']), 2) for s in snapshots]
    
    # 收益率（相对于 initial_cash）
    returns = [
        round((float(s['total_value']) - initial_cash) / initial_cash * 100, 2)
        for s in snapshots
    ]
    
    # 基准线（沪深300 近似：这里用 0 代替，前端可叠加真实基准）
    benchmark = [0] * len(dates)
    
    return jsonify({
        'dates': dates,
        'total_asset': total_assets,
        'returns': returns,
        'benchmark': benchmark,
        'initial_cash': initial_cash,
    })


# ====================================================================
#  API: PM 快捷操作
# ====================================================================
PM_ALLOWED_TYPES = {"story", "bug"}
PM_ALLOWED_PRIORITIES = {"P0", "P1", "P2", "P3", "S0", "S1", "S2", "S3"}
PM_ALLOWED_STATUSES = {"pending", "open", "in_progress", "testing", "fixed", "done", "verified", "reopened", "closed"}


def pm_db_path():
    """Return PM DB path; overridable in tests via app.config['PM_DB_PATH']."""
    return Path(app.config.get("PM_DB_PATH", ROOT / "data" / "pm.db"))


def pm_columns(conn):
    return {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}


def ensure_pm_schema(conn):
    """Create the minimal PM schema if missing; keep compatibility with extended schemas."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL,
            priority TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)


def next_pm_id(cursor, task_type):
    prefix = "REQ-" if task_type == "story" else "BUG-"
    cursor.execute("SELECT id FROM tasks WHERE id LIKE ?", (prefix + "%",))
    max_num = 0
    for row in cursor.fetchall():
        try:
            max_num = max(max_num, int(str(row[0]).split("-", 1)[1]))
        except Exception:
            continue
    return f"{prefix}{max_num + 1:03d}"


def append_work_note(existing, note):
    note = (note or "").strip()
    if not note:
        return existing
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {note}"
    return (str(existing or "").rstrip() + "\n" + line).strip()


@app.route('/api/pm/tasks', methods=['POST'])
def api_pm_create_task():
    """Quick-create a PM task from the dashboard action panel."""
    payload = request.get_json(silent=True) or {}
    task_type = str(payload.get('type', 'story')).strip()
    title = str(payload.get('title', '')).strip()
    description = str(payload.get('description', '')).strip()
    priority = str(payload.get('priority', 'P1')).strip().upper()

    if task_type not in PM_ALLOWED_TYPES:
        return jsonify({'status': 'error', 'msg': 'type must be story or bug'}), 400
    if not title:
        return jsonify({'status': 'error', 'msg': 'title is required'}), 400
    if priority not in PM_ALLOWED_PRIORITIES:
        return jsonify({'status': 'error', 'msg': 'invalid priority'}), 400

    initial_status = 'pending' if task_type == 'story' else 'open'
    db_path = pm_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        ensure_pm_schema(conn)
        cols = pm_columns(conn)
        cur = conn.cursor()
        task_id = next_pm_id(cur, task_type)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        values = {
            'id': task_id,
            'type': task_type,
            'title': title,
            'description': description,
            'status': initial_status,
            'priority': priority,
            'created_at': now,
            'updated_at': now,
            'work_notes': append_work_note('', 'created from PM quick action panel'),
        }
        use_cols = [c for c in values.keys() if c in cols]
        placeholders = ','.join(['?'] * len(use_cols))
        cur.execute(
            f"INSERT INTO tasks ({','.join(use_cols)}) VALUES ({placeholders})",
            [values[c] for c in use_cols],
        )
        conn.commit()

    return jsonify({'status': 'ok', 'task': {'id': task_id, 'type': task_type, 'title': title, 'status': initial_status, 'priority': priority}})


@app.route('/api/pm/tasks/<task_id>/status', methods=['POST'])
def api_pm_update_task_status(task_id):
    """Quick transition a PM task status from the dashboard action panel."""
    payload = request.get_json(silent=True) or {}
    new_status = str(payload.get('status', '')).strip()
    note = str(payload.get('note', '')).strip()
    if new_status not in PM_ALLOWED_STATUSES:
        return jsonify({'status': 'error', 'msg': 'invalid status'}), 400

    db_path = pm_db_path()
    with sqlite3.connect(db_path) as conn:
        ensure_pm_schema(conn)
        conn.row_factory = sqlite3.Row
        cols = pm_columns(conn)
        cur = conn.cursor()
        cur.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({'status': 'error', 'msg': f'{task_id} not found'}), 404

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        updates = ['status=?', 'updated_at=?']
        params = [new_status, now]
        if 'work_notes' in cols:
            updates.append('work_notes=?')
            params.append(append_work_note(row['work_notes'] if 'work_notes' in row.keys() else '', note or f'status -> {new_status} from PM quick action panel'))
        if 'result_notes' in cols and new_status in {'done', 'fixed', 'verified'} and note:
            updates.append('result_notes=?')
            params.append(note)
        params.append(task_id)
        cur.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id=?", params)
        conn.commit()

    return jsonify({'status': 'ok', 'task': {'id': task_id, 'status': new_status, 'updated_at': now}})

# ====================================================================
#  页面
# ====================================================================
@app.route('/')
def index():
    return send_from_directory(str(ROOT / 'web' / 'templates'), 'index.html')

@app.route('/api/pm_tasks')
def api_pm_tasks():
    pm_db = pm_db_path()
    try:
        with sqlite3.connect(pm_db) as conn:
            ensure_pm_schema(conn)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks ORDER BY priority ASC, updated_at DESC")
            tasks = [dict(r) for r in cursor.fetchall()]
            return jsonify({'status': 'ok', 'tasks': tasks})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)}), 500

@app.route('/pm')
def pm_board():
    return send_from_directory(str(ROOT / 'web' / 'templates'), 'pm.html')

if __name__ == '__main__':
    import os
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    print("启动持仓仪表盘 http://0.0.0.0:8080")
    app.run(host='0.0.0.0', port=8080, debug=False)
