import sqlite3
import os
from datetime import datetime

db_paths = [
    'data/trading.db',
    'data/market.db',
    'database/trading.db',
    'db.sqlite'
]

report = {
    'timestamp': datetime.now().isoformat(),
    'db_status': 'UNKNOWN',
    'details': []
}

for db_path in db_paths:
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
            tables = cursor.fetchall()
            
            test_table = '_health_check_'
            cursor.execute('CREATE TABLE IF NOT EXISTS ' + test_table + ' (id INTEGER PRIMARY KEY, ts DATETIME)')
            cursor.execute('INSERT INTO ' + test_table + ' (ts) VALUES (?)', (datetime.now(),))
            conn.commit()
            cursor.execute('DROP TABLE IF EXISTS ' + test_table)
            conn.commit()
            
            conn.close()
            
            report['db_status'] = 'OK'
            report['details'].append(f'{db_path}: 可读写，找到 {len(tables)} 个表')
            break
        except Exception as e:
            report['details'].append(f'{db_path}: {str(e)}')

if report['db_status'] == 'UNKNOWN':
    try:
        conn = sqlite3.connect(':memory:')
        conn.close()
        report['db_status'] = 'WARNING'
        report['details'].append('未找到数据库文件，但 SQLite 可用')
    except Exception as e:
        report['db_status'] = 'ERROR'
        report['details'].append(f'SQLite 不可用: {str(e)}')

print(report)
