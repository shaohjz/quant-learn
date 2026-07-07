"""Daily review helper - inspect PM DB and sim DB."""
import sqlite3
import json
import os

BASE = r"C:\Users\Administrator\.openclaw\workspace\quant-learn"

def inspect_db(path, label):
    print(f"\n{'='*60}")
    print(f"  {label}: {path}")
    print(f"{'='*60}")
    if not os.path.exists(path):
        print(f"  [MISSING] File not found!")
        return
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f"  Tables: {tables}")
    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM [{t}]")
        count = cur.fetchone()[0]
        print(f"\n  --- {t} ({count} rows) ---")
        cur.execute(f"PRAGMA table_info([{t}])")
        cols = [c[1] for c in cur.fetchall()]
        print(f"  Columns: {cols}")
        cur.execute(f"SELECT * FROM [{t}] LIMIT 50")
        rows = cur.fetchall()
        for row in rows:
            print(f"    {dict(zip(cols, row))}")
    conn.close()

# Inspect PM DB
inspect_db(os.path.join(BASE, "data", "pm.db"), "PM Database")

# Inspect Sim DB
inspect_db(os.path.join(BASE, "data", "sim_live_mirror.db"), "Sim Live Mirror DB")

# Check git status
print(f"\n{'='*60}")
print(f"  Git Status")
print(f"{'='*60}")
import subprocess
result = subprocess.run(["git", "-C", BASE, "status", "--short"], capture_output=True, text=True)
print(result.stdout or "(clean)")

# Check project structure
print(f"\n{'='*60}")
print(f"  Key Project Files")
print(f"{'='*60}")
for root, dirs, files in os.walk(BASE):
    dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', 'node_modules', '.venv', 'venv')]
    for f in files:
        if f.endswith('.py'):
            rel = os.path.relpath(os.path.join(root, f), BASE)
            if any(kw in rel for kw in ['web/app', 'sim/engine', 'sim/trade', 'auto_trader', 'daily']):
                print(f"  {rel}")
    if len(root) - len(BASE) > 50:
        break
