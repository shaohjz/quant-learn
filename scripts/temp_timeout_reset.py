import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "pm.db"

def reset_timeout_tasks():
    hours = 2  # 超时阈值：2小时
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, status, updated_at FROM tasks WHERE status='in_progress'"
        )
        rows = cursor.fetchall()
        now = datetime.now()
        reset_count = 0
        
        print(f"Checking {len(rows)} in_progress task(s)...")
        for r in rows:
            try:
                updated = datetime.strptime(r['updated_at'], "%Y-%m-%d %H:%M:%S")
                diff_hours = (now - updated).total_seconds() / 3600
                if diff_hours > hours:
                    cursor.execute(
                        "UPDATE tasks SET status='pending', updated_at=? WHERE id=?",
                        (now.strftime("%Y-%m-%d %H:%M:%S"), r['id'])
                    )
                    print(f"⏰ Timeout reset: {r['id']} ({r['title']}) — in_progress for {diff_hours:.1f}h")
                    reset_count += 1
            except Exception as e:
                print(f"Skip {r['id']}: {e}")
        
        conn.commit()
        print(f"Total reset: {reset_count} task(s)")

if __name__ == "__main__":
    reset_timeout_tasks()
