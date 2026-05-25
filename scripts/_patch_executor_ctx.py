"""Patch sim_executor: 记录完整交易决策上下文"""
from pathlib import Path

f = Path('scripts/sim_executor.py')
text = f.read_text(encoding='utf-8')

# 1. 改 insert_trade 函数签名和实现
old_func = '''def insert_trade(code: str, name: str, direction: str, price: float, qty: int,
                 commission: float, tax: float, signal_reason: str):
    from datetime import datetime as _dt
    now = _dt.now()
    trade_time_str = now.strftime('%H:%M:%S')  # 北京时间 HH:MM:SS
    conn = get_conn()
    conn.execute(
        """INSERT INTO sim_trades 
           (account_id, trade_date, stock_code, stock_name, direction, price, quantity, amount, commission, tax, signal_reason, broker, trade_time)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (_ACCOUNT_ID, date.today().isoformat(), code, name, direction, price, qty, price*qty,
         commission, tax, signal_reason, 'live_mirror' if _ACCOUNT_ID == 1 else 'real_mirror', trade_time_str)
    )
    conn.close()'''

new_func = '''def insert_trade(code: str, name: str, direction: str, price: float, qty: int,
                 commission: float, tax: float, signal_reason: str, trade_context: dict = None):
    import json as _json
    from datetime import datetime as _dt
    now = _dt.now()
    trade_time_str = now.strftime('%H:%M:%S')  # 北京时间 HH:MM:SS
    ctx_json = _json.dumps(trade_context, ensure_ascii=False) if trade_context else None
    conn = get_conn()
    conn.execute(
        """INSERT INTO sim_trades 
           (account_id, trade_date, stock_code, stock_name, direction, price, quantity, amount, commission, tax, signal_reason, broker, trade_time, trade_context)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (_ACCOUNT_ID, date.today().isoformat(), code, name, direction, price, qty, price*qty,
         commission, tax, signal_reason, 'live_mirror' if _ACCOUNT_ID == 1 else 'real_mirror', trade_time_str, ctx_json)
    )
    conn.close()'''

text = text.replace(old_func, new_func)

# 2. 在卖出调用 insert_trade 时传入 context
old_sell = '''        insert_trade(code, name, 'SELL', cur_price, sell_qty, commission, tax,
                     f"自动: {rule['level']} | {rule['message'][:30]}")'''

new_sell = '''        _sell_ctx = {
            'strategy': '阈值触发',
            'rule_level': rule['level'],
            'trigger_price': rule.get('trigger', 0),
            'signal_msg': rule.get('message', ''),
            'sell_reason': f"触发{rule['level']}卖出规则",
            'price_at_trigger': cur_price,
            'position_qty_before': pos['quantity'],
            'avg_cost': pos['avg_cost'],
            'pnl_pct': round((cur_price - pos['avg_cost']) / pos['avg_cost'] * 100, 2),
        }
        insert_trade(code, name, 'SELL', cur_price, sell_qty, commission, tax,
                     f"自动: {rule['level']} | {rule['message'][:50]}",
                     trade_context=_sell_ctx)'''

text = text.replace(old_sell, new_sell)

# 3. 在买入调用 insert_trade 时传入 context
old_buy = '''        insert_trade(code, name, 'BUY', cur_price, buy_qty, commission, 0,
                     f"自动: {rule['level']} | {rule['message'][:30]}")'''

new_buy = '''        _buy_ctx = {
            'strategy': '阈值触发',
            'rule_level': rule['level'],
            'trigger_price': rule.get('trigger', 0),
            'signal_msg': rule.get('message', ''),
            'buy_type': action,  # BUY_LIGHT / BUY_HEAVY
            'budget': round(budget, 0),
            'price_at_trigger': cur_price,
            'ma_info': rule.get('message', ''),  # MA10/MA20 信息在 message 里
        }
        insert_trade(code, name, 'BUY', cur_price, buy_qty, commission, 0,
                     f"自动: {rule['level']} | {rule['message'][:50]}",
                     trade_context=_buy_ctx)'''

text = text.replace(old_buy, new_buy)

f.write_text(text, encoding='utf-8')
print("✓ sim_executor patched")
