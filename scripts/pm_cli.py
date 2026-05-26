import sys
import sqlite3
import argparse
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "pm.db"

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL,
                priority TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()

def generate_id(cursor, task_type):
    prefix = "REQ-" if task_type == "story" else "BUG-"
    cursor.execute("SELECT id FROM tasks WHERE type=? ORDER BY id DESC LIMIT 1", (task_type,))
    row = cursor.fetchone()
    if row:
        last_num = int(row[0].split("-")[1])
        new_num = last_num + 1
    else:
        new_num = 1
    return f"{prefix}{new_num:03d}"

def cmd_create(args):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        new_id = generate_id(cursor, args.type)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO tasks (id, type, title, description, status, priority, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, args.type, args.title, args.desc, args.status, args.priority, now, now)
        )
        conn.commit()
        print(f"Created {new_id}: {args.title}")

def cmd_update(args):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        updates = []
        params = []
        if args.status:
            updates.append("status=?")
            params.append(args.status)
        if args.priority:
            updates.append("priority=?")
            params.append(args.priority)
        if args.title:
            updates.append("title=?")
            params.append(args.title)
        
        if not updates:
            print("Nothing to update.")
            return

        updates.append("updated_at=?")
        params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        params.append(args.id)

        cursor.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id=?", params)
        if cursor.rowcount == 0:
            print(f"Task {args.id} not found.")
        else:
            conn.commit()
            print(f"Updated {args.id}")

def cmd_list(args):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = "SELECT * FROM tasks"
        filters = []
        params = []
        if args.status:
            filters.append("status=?")
            params.append(args.status)
        if args.type:
            filters.append("type=?")
            params.append(args.type)
        
        if filters:
            query += " WHERE " + " AND ".join(filters)
        
        query += " ORDER BY updated_at DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        for r in rows:
            print(f"[{r['id']}] ({r['status']}) [{r['priority']}] {r['title']}")

def cmd_dedup(args):
    """ 去重脚本 """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, type FROM tasks WHERE status IN ('pending', 'open')")
        tasks = cursor.fetchall()
        
        seen_titles = {}
        duplicates = []
        for t in tasks:
            title = t['title'].strip().lower()
            if title in seen_titles:
                duplicates.append(t['id'])
            else:
                seen_titles[title] = t['id']
                
        if not duplicates:
            print("No duplicates found.")
            return
            
        for dup_id in duplicates:
            print(f"Removing duplicate task: {dup_id}")
            cursor.execute("DELETE FROM tasks WHERE id=?", (dup_id,))
        conn.commit()
        print(f"Removed {len(duplicates)} duplicates.")

def main():
    init_db()
    parser = argparse.ArgumentParser(description="QuantLearn PM CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Create
    p_create = subparsers.add_parser("create", help="Create a new task")
    p_create.add_argument("type", choices=["story", "bug"], help="Task type")
    p_create.add_argument("title", help="Task title")
    p_create.add_argument("--desc", default="", help="Task description")
    p_create.add_argument("--status", default="pending", help="Initial status (pending, open, etc.)")
    p_create.add_argument("--priority", default="P1", help="Priority (P0, P1, S0, etc.)")

    # Update
    p_update = subparsers.add_parser("update", help="Update a task")
    p_update.add_argument("id", help="Task ID (e.g., REQ-001)")
    p_update.add_argument("--status", help="New status")
    p_update.add_argument("--priority", help="New priority")
    p_update.add_argument("--title", help="New title")

    # List
    p_list = subparsers.add_parser("list", help="List tasks")
    p_list.add_argument("--status", help="Filter by status")
    p_list.add_argument("--type", choices=["story", "bug"], help="Filter by type")
    
    # Dedup
    p_dedup = subparsers.add_parser("dedup", help="Deduplicate pending tasks based on title")

    args = parser.parse_args()
    if args.command == "create":
        cmd_create(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "dedup":
        cmd_dedup(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
