"""把 cmd_report 函数插入 pm_cli.py"""
with open(r"C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts\pm_cli.py", "r", encoding="utf-8") as f:
    content = f.read()

cmd_report_fn = '''
def cmd_report(args):
    """生成小时汇报 JSON（给 PM Agent 用）"""
    now = datetime.now()
    since = (now - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 任务统计
    cur.execute("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status")
    status_stats = {r['status']: r['cnt'] for r in cur.fetchall()}

    # 最近 1h commit
    try:
        import subprocess
        log_out = subprocess.check_output(
            ['git', 'log', '--oneline', f'--since={since}'],
            cwd=str(ROOT), stderr=subprocess.DEVNULL
        ).decode('utf-8', errors='replace').strip()
        commits = log_out.splitlines() if log_out else []
    except Exception:
        commits = []

    # in_progress 超时检查（>3h）
    cur.execute("SELECT id, title, updated_at FROM tasks WHERE status='in_progress'")
    stuck = []
    for r in cur.fetchall():
        try:
            upd = datetime.strptime(r['updated_at'], '%Y-%m-%d %H:%M:%S')
            if (now - upd).total_seconds() > 10800:
                stuck.append({'id': r['id'], 'title': r['title']})
        except Exception:
            pass

    conn.close()

    report = {
        'time': now.strftime('%H:%M'),
        'tasks': status_stats,
        'recent_commits': commits[:5],
        'stuck_tasks': stuck,
        'pending_count': status_stats.get('pending', 0),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


'''

# 插入到 if __name__ == "__main__": 之前
marker = 'if __name__ == "__main__":'
if marker in content:
    new_content = content.replace(marker, cmd_report_fn + "\n" + marker)
    with open(r"C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts\pm_cli.py", "w", encoding="utf-8") as f:
        f.write(new_content)
    print("OK: cmd_report inserted")
else:
    print("ERROR: marker not found")
