"""
持仓 Web 仪表盘 v2 — 参考券商APP设计
端口: 8080
"""
import sys, json, sqlite3, re
from pathlib import Path
from datetime import datetime, date, timedelta
from flask import Flask, jsonify, send_from_directory
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
                    prices[code] = {
                        'name': parts[0],
                        'price': float(parts[3]),
                        'yclose': float(parts[2]),
                        'open': float(parts[1]),
                        'high': float(parts[4]),
                        'low': float(parts[5]),
                        'volume': float(parts[8]),
                        'amount': float(parts[9]),
                        'pct': round((float(parts[3]) - float(parts[2])) / float(parts[2]) * 100, 2) if float(parts[2]) > 0 else 0,
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
    acc = acc[0] if acc else {'cash': 0}
    
    codes = [p['stock_code'] for p in positions]
    rt = get_sina_prices(codes)
    
    result = []
    total_mv = 0
    total_pnl = 0
    for p in positions:
        code = p['stock_code']
        cur = rt.get(code, {}).get('price', p.get('avg_cost', 0))
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
            'total_asset': round(total_asset, 2),
            'total_return_pct': round((total_asset - 100000) / 100000 * 100, 2),
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
        # 用 buy_zone trigger 作为加入时的参考价
        rules = info.get('rules', {})
        ref_price = 0
        if isinstance(rules, dict):
            bz = rules.get('buy_zone', {})
            if isinstance(bz, dict):
                ref_price = bz.get('trigger', 0)
        since_pct = round((price - ref_price) / ref_price * 100, 1) if ref_price > 0 and price > 0 else None
        
        result.append({
            'code': code,
            'name': info.get('name', rt.get(code, {}).get('name', '')),
            'source': info.get('source', '手动添加'),
            'added_at': added_at,
            'added_reason': info.get('added_reason', ''),
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
        result.append({
            'code': code,
            'name': info.get('name', rt.get(code, {}).get('name', '')),
            'source': info.get('source', 'intraday_scanner'),
            'added_at': str(info.get('added_at', '')),
            'added_reason': info.get('added_reason', ''),
            'tags': [],
            'price': round(price, 2),
            'pct_today': round(pct_today, 2),
            'since_pct': None,
            'category': 'auto_discovered',
            'buy_zone': info.get('buy_zone', 0),
            'buy_strong': info.get('buy_strong', 0),
        })
    
    return jsonify({'watchlist': result, 'updated_at': datetime.now().strftime('%H:%M:%S')})

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
    since = (date.today() - timedelta(days=7)).isoformat()
    trades = query_db(
        "SELECT trade_date, direction, amount FROM sim_trades WHERE account_id=1 AND trade_date >= ?",
        (since,)
    )
    buy_count = sum(1 for t in trades if t['direction'] == 'BUY')
    sell_count = sum(1 for t in trades if t['direction'] == 'SELL')
    buy_amount = sum(t.get('amount', 0) or 0 for t in trades if t['direction'] == 'BUY')
    sell_amount = sum(t.get('amount', 0) or 0 for t in trades if t['direction'] == 'SELL')
    
    # 胜率(有盈利的卖出 / 总卖出)
    all_sells = query_db(
        "SELECT stock_code, price as sell_price FROM sim_trades WHERE account_id=1 AND direction='SELL' ORDER BY created_at DESC LIMIT 20"
    )
    
    return jsonify({
        'week_trades': {
            'buy_count': buy_count,
            'sell_count': sell_count,
            'buy_amount': round(buy_amount, 0),
            'sell_amount': round(sell_amount, 0),
        },
        'total_trades': len(query_db("SELECT id FROM sim_trades WHERE account_id=1")),
    })

# ====================================================================
#  页面
# ====================================================================
@app.route('/')
def index():
    return send_from_directory(str(ROOT / 'web' / 'templates'), 'index.html')

if __name__ == '__main__':
    print("🚀 启动持仓仪表盘 http://0.0.0.0:8080")
    app.run(host='0.0.0.0', port=8080, debug=False)
