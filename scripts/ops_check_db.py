import sqlite3, os
from datetime import datetime

dbs = [
    r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\pm.db',
    r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim.db',
    r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db',
]

print('=== 数据库可读写检查 ===')
db_results = {}
for db_path in dbs:
    name = os.path.basename(db_path)
    if not os.path.exists(db_path):
        print('SKIP ' + name + ': 文件不存在')
        db_results[name] = 'SKIP'
        continue
    try:
        conn = sqlite3.connect(db_path, timeout=3)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 5")
        tables = cursor.fetchall()
        test_table = '_ops_health_check_' + datetime.now().strftime('%Y%m%d%H%M%S')
        cursor.execute('CREATE TABLE IF NOT EXISTS [' + test_table + '] (id INTEGER PRIMARY KEY, ts TEXT)')
        cursor.execute('INSERT INTO [' + test_table + '] (ts) VALUES (?)', (datetime.now().isoformat(),))
        conn.commit()
        cursor.execute('DROP TABLE IF EXISTS [' + test_table + ']')
        conn.commit()
        conn.close()
        tbl_list = [t[0] for t in tables]
        print('OK ' + name + ': 可读写, tables=' + str(tbl_list))
        db_results[name] = 'OK'
    except Exception as e:
        print('FAIL ' + name + ': ' + str(e))
        db_results[name] = 'FAIL'

print()
ok_count = sum(1 for v in db_results.values() if v == 'OK')
all_count = sum(1 for v in db_results.values() if v != 'SKIP')
print('DB check: ' + str(ok_count) + '/' + str(all_count) + ' OK')
