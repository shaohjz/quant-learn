import sqlite3, json, os

db_path = 'data/pm.db'
if not os.path.exists(db_path):
    print(f"DB not found: {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 检查表结构
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]
print('Tables:', tables)

# 统计各状态任务数量
status_summary = {}
for table in tables:
    cursor.execute(f'SELECT status, COUNT(*) as cnt FROM "{table}" GROUP BY status')
    status_summary[table] = {}
    print(f'\n{table} status distribution:')
    for row in cursor.fetchall():
        status = row["status"]
        cnt = row["cnt"]
        status_summary[table][status] = cnt
        print(f'  {status}: {cnt}')

# 获取所有任务详情
all_tasks = {}
for table in tables:
    cursor.execute(f'SELECT * FROM "{table}" ORDER BY status')
    rows = cursor.fetchall()
    print(f'\n=== {table} ===')
    tasks = []
    for row in rows:
        d = dict(row)
        tasks.append(d)
        print(json.dumps(d, ensure_ascii=False, default=str))
    all_tasks[table] = tasks

conn.close()

# 输出汇总 JSON
print('\n=== SUMMARY ===')
output = {
    "tables": tables,
    "status_summary": status_summary,
    "all_tasks": all_tasks
}
with open('data/pm_status_snapshot.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, default=str, indent=2)
print("Snapshot saved to data/pm_status_snapshot.json")
