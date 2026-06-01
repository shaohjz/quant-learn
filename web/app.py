"""
持仓 Web 仪表盘 v2 — 参考券商APP设计
端口: 8080
"""
import sys, json, sqlite3, re
from pathlib import Path
from datetime import datetime, date, timedelta
from flask import Flask, jsonify, send_from_directory, render_template_string
import yaml

ROOT = Path(__file__).resolve().parents[1]
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
def query_db(sql, params=()):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ====================================================================
#  API: 模拟盘
# ====================================================================
@app.route('/api/portfolio')
def api_portfolio():
    positions = query_db("SELECT * FROM sim_positions WHERE account_id=1 AND quantity > 0")
    acc = query_db("SELECT * FROM sim_account WHERE id=1")
    acc = acc[0] if acc else {'cash': 0, 'initial_cash': 0}
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding='utf-8')) or {}
    initial_cash = float(
        cfg.get('accounts', {}).get('learn', {}).get(
            'initial_cash', acc.get('initial_cash') or 200000
        )
    )
    
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
    
    total_asset = acc.get('cash', 0) + total_mv
    return jsonify({
        'account': {
            'cash': round(acc.get('cash', 0), 2),
            'initial_cash': round(initial_cash, 2),
            'total_asset': round(total_asset, 2),
            'total_return_pct': round((total_asset - initial_cash) / initial_cash * 100, 2) if initial_cash > 0 else 0,
            'position_pct': round(total_mv / total_asset * 100, 1) if total_asset > 0 else 0,
        },
        'positions': result,
        'total_market_value': round(total_mv, 2),
        'total_pnl': round(total_pnl, 2),
        'updated_at': datetime.now().strftime('%H:%M:%S'),
    })

# ====================================================================
#  API: 实盘
# ====================================================================
@app.route('/api/real_portfolio')
def api_real_portfolio():
    real_path = ROOT / "config_real.yaml"
    if not real_path.exists():
        return jsonify({'error': 'no config_real.yaml'})
    data = yaml.safe_load(real_path.read_text(encoding='utf-8'))
    acc = data.get('account', {})
    positions = data.get('positions', [])
    
    codes = [p['code'] for p in positions]
    rt = get_sina_prices(codes)
    
    result = []
    total_mv = 0
    total_pnl = 0
    for p in positions:
        code = p['code']
        cur = rt.get(code, {}).get('price', p['avg_cost'])
        pct_today = rt.get(code, {}).get('pct', 0)
        qty = p['quantity']
        cost = p['avg_cost']
        mv = cur * qty
        pnl = (cur - cost) * qty
        pnl_pct = (cur - cost) / cost * 100 if cost > 0 else 0
        total_mv += mv
        total_pnl += pnl
        result.append({
            'code': code,
            'name': p.get('name', rt.get(code, {}).get('name', '')),
            'quantity': qty,
            'avg_cost': round(cost, 3),
            'current_price': round(cur, 2),
            'pct_today': round(pct_today, 2),
            'market_value': round(mv, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
            'buy_reason': p.get('reason', '手动买入'),
            'high': rt.get(code, {}).get('high', 0),
            'low': rt.get(code, {}).get('low', 0),
            'amount': rt.get(code, {}).get('amount', 0),
        })
    
    cash = acc.get('cash', 0)
    init = acc.get('initial_capital', 25000)
    total_asset = cash + total_mv
    return jsonify({
        'account': {
            'cash': round(cash, 2),
            'total_asset': round(total_asset, 2),
            'total_return_pct': round((total_asset - init) / init * 100, 2),
            'position_pct': round(total_mv / total_asset * 100, 1) if total_asset > 0 else 0,
        },
        'positions': result,
        'total_market_value': round(total_mv, 2),
        'total_pnl': round(total_pnl, 2),
        'updated_at': datetime.now().strftime('%H:%M:%S'),
    })

# ====================================================================
#  API: 观察列表
# ====================================================================
@app.route('/api/watchlist')
def api_watchlist():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding='utf-8'))
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
    # 近7天交易统计
    since_week = (date.today() - timedelta(days=7)).isoformat()
    week_trades = query_db(
        "SELECT trade_date, direction, amount FROM sim_trades WHERE account_id=1 AND trade_date >= ?",
        (since_week,)
    )
    week_buy_count = sum(1 for t in week_trades if t['direction'] == 'BUY')
    week_sell_count = sum(1 for t in week_trades if t['direction'] == 'SELL')
    week_buy_amount = sum(t.get('amount', 0) or 0 for t in week_trades if t['direction'] == 'BUY')
    week_sell_amount = sum(t.get('amount', 0) or 0 for t in week_trades if t['direction'] == 'SELL')
    
    # 本月交易统计
    since_month = date.today().replace(day=1).isoformat()
    month_trades = query_db(
        "SELECT trade_date, direction, amount FROM sim_trades WHERE account_id=1 AND trade_date >= ?",
        (since_month,)
    )
    month_buy_count = sum(1 for t in month_trades if t['direction'] == 'BUY')
    month_sell_count = sum(1 for t in month_trades if t['direction'] == 'SELL')
    month_buy_amount = sum(t.get('amount', 0) or 0 for t in month_trades if t['direction'] == 'BUY')
    month_sell_amount = sum(t.get('amount', 0) or 0 for t in month_trades if t['direction'] == 'SELL')
    
    # 总交易统计
    all_trades = query_db("SELECT id, trade_date, direction, price, stock_code FROM sim_trades WHERE account_id=1")
    total_trades = len(all_trades)
    
    # 计算胜率：需要匹配买卖对
    # 简化：按股票代码匹配最近买入和卖出，判断盈亏
    win_count = 0
    total_closed = 0
    
    # 获取所有卖出交易
    sell_trades = query_db(
        "SELECT stock_code, price, trade_date FROM sim_trades WHERE account_id=1 AND direction='SELL' ORDER BY trade_date"
    )
    
    for sell in sell_trades:
        # 找到该股票在卖出前的最后买入价格
        buy_records = query_db(
            "SELECT price FROM sim_trades WHERE account_id=1 AND stock_code=? AND direction='BUY' AND trade_date <= ? ORDER BY trade_date DESC LIMIT 1",
            (sell['stock_code'], sell['trade_date'])
        )
        if buy_records:
            avg_cost = buy_records[0]['price']
            total_closed += 1
            if sell['price'] > avg_cost:
                win_count += 1
    
    win_rate = round(win_count / total_closed * 100, 1) if total_closed > 0 else 0
    
    # 计算平均持仓天数
    hold_days_list = []
    for sell in sell_trades:
        buy_records = query_db(
            "SELECT trade_date FROM sim_trades WHERE account_id=1 AND stock_code=? AND direction='BUY' AND trade_date <= ? ORDER BY trade_date DESC LIMIT 1",
            (sell['stock_code'], sell['trade_date'])
        )
        if buy_records:
            try:
                buy_date = datetime.strptime(buy_records[0]['trade_date'], '%Y-%m-%d').date()
                sell_date = datetime.strptime(sell['trade_date'], '%Y-%m-%d').date()
                hold_days_list.append((sell_date - buy_date).days)
            except:
                pass
    
    avg_hold_days = round(sum(hold_days_list) / len(hold_days_list), 1) if hold_days_list else 0
    
    # 最大单笔盈利/亏损
    max_profit_trade = {'code': '', 'pnl': 0}
    max_loss_trade = {'code': '', 'pnl': 0}
    
    for sell in sell_trades:
        buy_records = query_db(
            "SELECT price, quantity FROM sim_trades WHERE account_id=1 AND stock_code=? AND direction='BUY' AND trade_date <= ? ORDER BY trade_date DESC LIMIT 1",
            (sell['stock_code'], sell['trade_date'])
        )
        if buy_records:
            # 获取卖出数量
            sell_qty = query_db(
                "SELECT quantity FROM sim_trades WHERE account_id=1 AND stock_code=? AND direction='SELL' AND trade_date=? LIMIT 1",
                (sell['stock_code'], sell['trade_date'])
            )
            if sell_qty:
                qty = sell_qty[0]['quantity']
                pnl = (sell['price'] - buy_records[0]['price']) * qty
                if pnl > max_profit_trade['pnl']:
                    max_profit_trade = {'code': sell['stock_code'], 'pnl': round(pnl, 2)}
                if pnl < max_loss_trade['pnl']:
                    max_loss_trade = {'code': sell['stock_code'], 'pnl': round(pnl, 2)}
    
    return jsonify({
        'total_trades': total_trades,
        'win_rate': win_rate,
        'avg_hold_days': avg_hold_days,
        'max_profit_trade': max_profit_trade,
        'max_loss_trade': max_loss_trade,
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
    """获取近30天收益率曲线数据"""
    # 查询近30天的快照数据
    since_date = (date.today() - timedelta(days=30)).isoformat()
    snapshots = query_db(
        "SELECT snapshot_date, total_asset FROM daily_snapshot WHERE account_type='sim' AND snapshot_date >= ? ORDER BY snapshot_date",
        (since_date,)
    )
    
    if not snapshots:
        return jsonify({
            'dates': [],
            'returns': [],
            'benchmark': []
        })
    
    # 计算收益率
    dates = [s['snapshot_date'] for s in snapshots]
    initial_asset = snapshots[0]['total_asset']
    
    if initial_asset == 0:
        returns = [0] * len(snapshots)
    else:
        returns = [
            round((s['total_asset'] - initial_asset) / initial_asset * 100, 2)
            for s in snapshots
        ]
    
    # 基准线（假设为0，即不涨不跌）
    benchmark = [0] * len(dates)
    
    return jsonify({
        'dates': dates,
        'returns': returns,
        'benchmark': benchmark
    })

# ====================================================================
#  页面
# ====================================================================
@app.route('/')
def index():
    return send_from_directory(str(ROOT / 'web' / 'templates'), 'index.html')

@app.route('/api/pm_tasks')
def api_pm_tasks():
    pm_db = ROOT / "data" / "pm.db"
    try:
        with sqlite3.connect(pm_db) as conn:
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
    print("🚀 启动持仓仪表盘 http://0.0.0.0:8080")
    app.run(host='0.0.0.0', port=8080, debug=False)
