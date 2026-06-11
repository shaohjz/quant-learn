from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import yaml

CODE = '002453'
NAME = '华软科技'
QTY = 300
PRICE = 5.92
COMMISSION = 5.0
STAMP_TAX_RATE = 0.0005
GROSS = round(QTY * PRICE, 2)
STAMP_TAX = round(GROSS * STAMP_TAX_RATE, 4)
NET = round(GROSS - COMMISSION - STAMP_TAX, 4)
TODAY = datetime.now().strftime('%Y-%m-%d')
NOW = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
TRADE_TIME = datetime.now().strftime('%H:%M:%S')

# 1) config_real.yaml: authoritative real-portfolio display source.
real_path = Path('config_real.yaml')
real = yaml.safe_load(real_path.read_text(encoding='utf-8')) or {}
account = real.setdefault('account', {})
positions = real.setdefault('positions', [])
account['cash'] = round(float(account.get('cash', 0)) + NET, 4)
real['positions'] = [p for p in positions if p.get('code') != CODE]
# Conservative total_asset for display: cash + remaining positions at cost until realtime quote refresh fills market price.
remaining_value = sum(float(p.get('avg_cost', 0)) * int(p.get('quantity', 0)) for p in real['positions'])
account['total_asset'] = round(account['cash'] + remaining_value, 4)
real_path.write_text(yaml.safe_dump(real, allow_unicode=True, sort_keys=False), encoding='utf-8')

# 2) sim_live_mirror.db: account_id=2 real_portfolio mirror.
con = sqlite3.connect('data/sim_live_mirror.db')
con.row_factory = sqlite3.Row
try:
    cur = con.cursor()
    cur.execute('''
        INSERT INTO sim_trades (
            account_id, trade_date, trade_time, stock_code, stock_name, direction,
            price, quantity, amount, commission, tax, signal_reason, broker,
            created_at, trade_context
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        2, TODAY, TRADE_TIME, CODE, NAME, 'SELL', PRICE, QTY, GROSS,
        COMMISSION, STAMP_TAX,
        '用户实盘已按止损提醒卖出：5.92 卖出300股，机械止损线5.95已跌破',
        'real_portfolio_manual', NOW,
        '{"signal":"止损执行","strategy":"机械止损/风险控制","review":"跌破8%机械止损线，卖出合理"}',
    ))
    cur.execute('DELETE FROM sim_positions WHERE account_id=2 AND stock_code=?', (CODE,))
    # Keep account cash in sync with the real display file.
    total_value = float(account['total_asset'])
    cash = float(account['cash'])
    cur.execute('UPDATE sim_account SET cash=?, total_value=?, updated_at=? WHERE id=2', (cash, total_value, NOW))
    con.commit()
finally:
    con.close()

print(f'sold {CODE} qty={QTY} price={PRICE} gross={GROSS} net={NET}')
print(f'config_real cash={account["cash"]} total_asset={account["total_asset"]} positions={len(real["positions"])}')
