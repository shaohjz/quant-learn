#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
初始化模拟交易系统数据文件
"""

import json
import os
import sqlite3
from datetime import datetime

def init_data_files():
    """初始化所有数据文件"""
    
    # 创建storage目录
    os.makedirs('storage', exist_ok=True)
    
    print('开始初始化数据文件...')
    
    # 1. 创建 signal_watch.json（观察池）
    watch_data = {
        'stocks': [
            {'code': '688599', 'name': '天合光能', 'added_at': '2026-06-29'},
            {'code': '601615', 'name': '明阳智能', 'added_at': '2026-06-29'},
            {'code': '603218', 'name': '日月股份', 'added_at': '2026-06-29'},
            {'code': '002202', 'name': '金风科技', 'added_at': '2026-06-29'},
            {'code': '300772', 'name': '运达股份', 'added_at': '2026-06-29'},
            {'code': '601016', 'name': '节能风电', 'added_at': '2026-06-29'}
        ]
    }
    
    with open('storage/signal_watch.json', 'w', encoding='utf-8') as f:
        json.dump(watch_data, f, ensure_ascii=False, indent=2)
    
    print('✓ 创建 signal_watch.json')
    
    # 2. 创建 signal_watch.db（交易信号数据库）
    conn = sqlite3.connect('storage/signal_watch.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT,
            signal_type TEXT,
            price REAL,
            quantity INTEGER,
            created_at TEXT,
            status TEXT DEFAULT 'pending'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT,
            cost REAL,
            quantity INTEGER,
            buy_date TEXT,
            stop_loss REAL,
            take_profit REAL,
            status TEXT DEFAULT 'open'
        )
    ''')
    
    conn.commit()
    conn.close()
    
    print('✓ 创建 signal_watch.db')
    
    # 3. 创建/更新 broker.json（添加今早的6只持仓）
    broker_data = {
        'account': {
            'cash': 50000.0,  # 假设已使用5万买入
            'total_assets': 100000.0,
            'total_profit_ratio': 0.0,
            'update_time': '2026-06-29 11:00:16'
        },
        'positions': {
            '688599': {
                'name': '天合光能',
                'cost': 22.50,
                'quantity': 1000,
                'buy_date': '2026-06-29',
                'stop_loss': 20.70,
                'take_profit': 27.00,
                'current_price': 22.50
            },
            '601615': {
                'name': '明阳智能',
                'cost': 18.20,
                'quantity': 1200,
                'buy_date': '2026-06-29',
                'stop_loss': 16.74,
                'take_profit': 21.84,
                'current_price': 18.20
            },
            '603218': {
                'name': '日月股份',
                'cost': 15.80,
                'quantity': 1500,
                'buy_date': '2026-06-29',
                'stop_loss': 14.54,
                'take_profit': 18.96,
                'current_price': 15.80
            },
            '002202': {
                'name': '金风科技',
                'cost': 12.50,
                'quantity': 2000,
                'buy_date': '2026-06-29',
                'stop_loss': 11.50,
                'take_profit': 15.00,
                'current_price': 12.50
            },
            '300772': {
                'name': '运达股份',
                'cost': 14.20,
                'quantity': 1800,
                'buy_date': '2026-06-29',
                'stop_loss': 13.06,
                'take_profit': 17.04,
                'current_price': 14.20
            },
            '601016': {
                'name': '节能风电',
                'cost': 8.90,
                'quantity': 2500,
                'buy_date': '2026-06-29',
                'stop_loss': 8.19,
                'take_profit': 10.68,
                'current_price': 8.90
            }
        },
        'orders': [],
        'trades': [],
        'risk_settings': {
            'max_position_ratio': 0.3,
            'stop_loss_rate': -0.08,
            'take_profit_rate': 0.20,
            'max_drawdown': -0.15
        }
    }
    
    with open('storage/broker.json', 'w', encoding='utf-8') as f:
        json.dump(broker_data, f, ensure_ascii=False, indent=2)
    
    print('✓ 创建 broker.json，添加6只持仓')
    print('现金: 50000.0')
    print('持仓数量: 6')
    
    # 4. 记录买入信号到数据库
    conn = sqlite3.connect('storage/signal_watch.db')
    cursor = conn.cursor()
    
    buy_signals = [
        ('688599', '天合光能', 'BUY', 22.50, 1000),
        ('601615', '明阳智能', 'BUY', 18.20, 1200),
        ('603218', '日月股份', 'BUY', 15.80, 1500),
        ('002202', '金风科技', 'BUY', 12.50, 2000),
        ('300772', '运达股份', 'BUY', 14.20, 1800),
        ('601016', '节能风电', 'BUY', 8.90, 2500)
    ]
    
    for code, name, signal_type, price, quantity in buy_signals:
        cursor.execute('''
            INSERT INTO signals (code, name, signal_type, price, quantity, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (code, name, signal_type, price, quantity, '2026-06-29 09:35:00', 'filled'))
    
    conn.commit()
    conn.close()
    
    print('✓ 记录买入信号到数据库')
    print('\n初始化完成！')
    print('下一步: 运行 python scripts/update_positions.py 更新持仓价格')

if __name__ == '__main__':
    init_data_files()
