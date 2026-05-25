"""
持仓 Web 仪表盘 — Flask
端口: 8080 (云桌面对外开放)
"""
import sys, json, sqlite3, re
from pathlib import Path
from datetime import datetime, date
from flask import Flask, jsonify, send_from_directory
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

app = Flask(__name__, static_folder=str(ROOT / 'web' / 'templates'))
DB_PATH = ROOT / "data" / "sim_live_mirror.db"

# ====================================================================
#  实时行情
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
                prices[code] = {
                    'name': parts[0],
                    'price': float(parts[3]),
                    'yclose': float(parts[2]),
                    'pct': round((float(parts[3]) - float(parts[2])) / float(parts[2]) * 100, 2) if float(parts[2]) > 0 else 0,
                    'high': float(parts[4]),
                    'low': float(parts[5]),
                    'volume': float(parts[8]),
                    'amount': float(parts[9]),
                }
    return prices

# ====================================================================
#  数据库
# ====================================================================
def get_positions(account_id=1):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM sim_positions WHERE account_id=? AND quantity > 0", (account_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_account(account_id=1):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM sim_account WHERE id=?", (account_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}

def get_trades(account_id=1, limit=30):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM sim_trades WHERE account_id=? ORDER BY created_at DESC LIMIT ?",
        (account_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ====================================================================
#  实盘
# ====================================================================
def get_real_positions():
    real_path = ROOT / "config_real.yaml"
    if not real_path.exists():
        return None, []
    data = yaml.safe_load(real_path.read_text(encoding='utf-8'))
    return data.get('account', {}), data.get('positions', [])

# ====================================================================
#  API
# ====================================================================
@app.route('/api/portfolio')
def api_portfolio():
    acc = get_account(1)
    positions = get_positions(1)
    codes = [p['stock_code'] for p in positions]
    rt = get_sina_prices(codes) if codes else {}
    
    result = []
    total_mv = 0
    total_pnl = 0
    for p in positions:
        code = p['stock_code']
        cur = rt.get(code, {}).get('price', p.get('current_price', 0))
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
            'name': p.get('stock_name', rt.get(code, {}).get('name', '')),
            'quantity': qty,
            'avg_cost': round(cost, 3),
            'current_price': round(cur, 3),
            'pct_today': round(pct_today, 2),
            'market_value': round(mv, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
        })
    
    total_asset = acc.get('cash', 0) + total_mv
    return jsonify({
        'account': {
            'cash': round(acc.get('cash', 0), 2),
            'total_asset': round(total_asset, 2),
            'total_return_pct': round((total_asset - 100000) / 100000 * 100, 2),
        },
        'positions': result,
        'total_market_value': round(total_mv, 2),
        'total_pnl': round(total_pnl, 2),
        'updated_at': datetime.now().strftime('%H:%M:%S'),
    })

@app.route('/api/real_portfolio')
def api_real_portfolio():
    acc, positions = get_real_positions()
    if not positions:
        return jsonify({'error': 'no real positions configured'})
    
    codes = [p['code'] for p in positions]
    rt = get_sina_prices(codes)
    
    result = []
    total_mv = 0
    total_pnl = 0
    for p in positions:
        code = p['code']
        cur = rt.get(code, {}).get('price', 0)
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
            'current_price': round(cur, 3),
            'pct_today': round(pct_today, 2),
            'market_value': round(mv, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
        })
    
    cash = acc.get('cash', 0)
    init_capital = acc.get('initial_capital', 25000)
    total_asset = cash + total_mv
    
    return jsonify({
        'account': {
            'cash': round(cash, 2),
            'total_asset': round(total_asset, 2),
            'total_return_pct': round((total_asset - init_capital) / init_capital * 100, 2),
            'position_pct': round(total_mv / total_asset * 100, 1) if total_asset > 0 else 0,
        },
        'positions': result,
        'total_market_value': round(total_mv, 2),
        'total_pnl': round(total_pnl, 2),
        'updated_at': datetime.now().strftime('%H:%M:%S'),
    })

@app.route('/api/trades')
def api_trades():
    trades = get_trades(1, 30)
    return jsonify({'trades': trades})

@app.route('/api/stock_trades/<code>')
def api_stock_trades(code):
    """查询单只股票的交易历史"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT trade_date, trade_time, direction, quantity, price, amount FROM sim_trades WHERE stock_code=? ORDER BY created_at DESC LIMIT 20",
        (code,)
    ).fetchall()
    conn.close()
    return jsonify({'trades': [dict(r) for r in rows]})

@app.route('/')
def index():
    return send_from_directory(str(ROOT / 'web' / 'templates'), 'index.html')

if __name__ == '__main__':
    print("🚀 启动持仓仪表盘 http://0.0.0.0:8080")
    app.run(host='0.0.0.0', port=8080, debug=False)
