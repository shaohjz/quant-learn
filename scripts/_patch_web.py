"""Patch web/app.py: 加入实盘持仓 API"""
from pathlib import Path

f = Path('web/app.py')
text = f.read_text(encoding='utf-8')

# 1. 加入 yaml import 和实盘 API
api_code = '''
# ====================================================================
#  实盘持仓
# ====================================================================
def get_real_positions():
    """读取实盘持仓"""
    import yaml as _yaml
    real_path = ROOT / "config_real.yaml"
    if not real_path.exists():
        return None, []
    data = _yaml.safe_load(real_path.read_text(encoding='utf-8'))
    return data.get('account', {}), data.get('positions', [])

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

'''

# 在 @app.route('/api/trades') 之前插入
text = text.replace("@app.route('/api/trades')", api_code + "@app.route('/api/trades')")

f.write_text(text, encoding='utf-8')
print("OK - API added")
