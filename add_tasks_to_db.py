#!/usr/bin/env python3
"""Add tasks to QuantLearn PM database from command line arguments.

This script allows adding tasks to the pm.db database with proper
command line argument parsing.

Usage:
    python add_tasks_to_db.py --id REQ-001 --type story --title "Task title" \
                              --desc "Description" --status pending --priority P1

Or import as module:
    from add_tasks_to_db import add_task
    add_task(id='REQ-001', type='story', title='...', ...)
"""

import sqlite3
import argparse
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "pm.db"


def init_db():
    """Initialize the database with tasks table if it doesn't exist."""
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


def add_task(id, type, title, description="", status="pending", priority="P1"):
    """Add a single task to the database.
    
    Args:
        id: Task ID (e.g., REQ-001, BUG-001)
        type: Task type ("story" or "bug")
        title: Task title
        description: Task description (optional)
        status: Task status (default: "pending")
        priority: Task priority (default: "P1")
    
    Returns:
        bool: True if task was added successfully, False if it already exists
    """
    init_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO tasks (id, type, title, description, status, priority, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (id, type, title, description, status, priority, now, now)
            )
            conn.commit()
            print(f"✓ Added task: {id} - {title}")
            return True
    except sqlite3.IntegrityError:
        print(f"✗ Task {id} already exists")
        return False


def add_tasks_from_list(tasks):
    """Add multiple tasks from a list of task dictionaries.
    
    Args:
        tasks: List of dictionaries with keys: id, type, title, 
               description (optional), status (optional), priority (optional)
    
    Returns:
        tuple: (success_count, failed_count)
    """
    success = 0
    failed = 0
    
    for task in tasks:
        if add_task(**task):
            success += 1
        else:
            failed += 1
    
    return success, failed


def main():
    """Main function with command line argument parsing."""
    parser = argparse.ArgumentParser(
        description="Add tasks to QuantLearn PM database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python add_tasks_to_db.py --id REQ-001 --type story --title "My task"
  python add_tasks_to_db.py --id BUG-001 --type bug --title "Fix bug" --priority P0
  python add_tasks_to_db.py --file tasks.json
        """
    )
    
    # Single task mode
    parser.add_argument("--id", help="Task ID (e.g., REQ-001)")
    parser.add_argument("--type", choices=["story", "bug"], help="Task type")
    parser.add_argument("--title", help="Task title")
    parser.add_argument("--desc", default="", help="Task description")
    parser.add_argument("--status", default="pending", help="Task status (default: pending)")
    parser.add_argument("--priority", default="P1", help="Task priority (default: P1)")
    
    # Batch mode from file
    parser.add_argument("--file", help="JSON file containing tasks to add")
    
    # Demo mode
    parser.add_argument("--demo", action="store_true", help="Add demo tasks")
    
    args = parser.parse_args()
    
    # Demo mode
    if args.demo:
        demo_tasks = [
            {
                "id": "REQ-042",
                "type": "story",
                "title": "量化通知/盘中盯盘 去大模型化 — 纯代码 + 企微 Webhook 直推",
                "description": "当前所有量化通知都依赖大模型推理，消耗大量token且有延迟。需要改造为纯代码脚本直接调用企微Webhook",
                "status": "pending",
                "priority": "P1"
            },
            {
                "id": "REQ-044",
                "type": "story",
                "title": "职业理财经理 Agent — 定时复盘 + 提改进需求",
                "description": "创建职业理财经理Agent，每天收盘后自动复盘并提出改进需求",
                "status": "pending",
                "priority": "P0"
            }
        ]
        
        print("Adding demo tasks...")
        success, failed = add_tasks_from_list(demo_tasks)
        print(f"\nSummary: {success} added, {failed} failed")
        return
    
    # File mode
    if args.file:
        import json
        with open(args.file, 'r', encoding='utf-8') as f:
            tasks = json.load(f)
        
        if isinstance(tasks, list):
            print(f"Adding {len(tasks)} tasks from {args.file}...")
            success, failed = add_tasks_from_list(tasks)
            print(f"\nSummary: {success} added, {failed} failed")
        else:
            print("Error: JSON file must contain a list of tasks")
        return
    
    # Single task mode
    if not all([args.id, args.type, args.title]):
        parser.print_help()
        return
    
    add_task(
        id=args.id,
        type=args.type,
        title=args.title,
        description=args.desc,
        status=args.status,
        priority=args.priority
    )


if __name__ == "__main__":
    main()
