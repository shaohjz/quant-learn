#!/usr/bin/env python3
"""QuantLearn PM CLI — 真源为 Markdown（scripts/pm_store.py），不再写 pm.db tasks。"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pm_store import (  # noqa: E402
    append_work_note,
    get_task,
    list_tasks,
    next_id,
    status_counts,
    update_task,
    upsert_task,
    write_backlog,
)


def cmd_create(args):
    t = upsert_task(
        type=args.type,
        title=args.title,
        description=args.desc or "",
        status=args.status,
        priority=args.priority,
    )
    print(f"Created {t['id']}: {t['title']} → {t['path']}")


def cmd_update(args):
    fields = {}
    if args.status:
        fields["status"] = args.status
    if args.priority:
        fields["priority"] = args.priority
    if args.title:
        fields["title"] = args.title
    if getattr(args, "note", None):
        append_work_note(args.id, args.note)
    if not fields and not getattr(args, "note", None):
        print("Nothing to update.")
        return
    t = update_task(args.id, **fields) if fields else get_task(args.id)
    if not t:
        print(f"Task {args.id} not found.")
        return
    print(f"Updated {t['id']} status={t.get('status')} → {t.get('path')}")


def cmd_get(args):
    t = get_task(args.id)
    if not t:
        print(f"Task {args.id} not found.")
        return 1
    print(json.dumps({k: v for k, v in t.items() if k != "body"}, ensure_ascii=False, indent=2))
    return 0


def cmd_list(args):
    rows = list_tasks(status=args.status, type=args.type, include_archive=bool(args.archive))
    for r in rows:
        print(f"[{r['id']}] ({r['status']}) [{r['priority']}] {r['title']}")
    if args.write_backlog:
        p = write_backlog()
        print(f"Wrote {p}")


def cmd_timeout_reset(args):
    hours = args.hours or 6
    now = datetime.now()
    reset_count = 0
    for r in list_tasks():
        if str(r.get("status")) != "in_progress":
            continue
        raw = r.get("updated_at") or ""
        try:
            try:
                updated = datetime.strptime(str(raw), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                updated = datetime.strptime(str(raw)[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception as e:
            print(f"Skip {r['id']}: {e}")
            continue
        diff_hours = (now - updated).total_seconds() / 3600
        if diff_hours > hours:
            update_task(r["id"], status="pending")
            append_work_note(r["id"], f"timeout reset after {diff_hours:.1f}h in_progress")
            print(f"Timeout reset: {r['id']} ({r['title']}) — {diff_hours:.1f}h")
            reset_count += 1
    print(f"Total reset: {reset_count} task(s)")


def cmd_dedup(args):
    seen = {}
    duplicates = []
    for t in list_tasks():
        if str(t.get("status")) not in ("pending", "open"):
            continue
        title = str(t.get("title") or "").strip().lower()
        if title in seen:
            duplicates.append(t["id"])
        else:
            seen[title] = t["id"]
    if not duplicates:
        print("No duplicates found.")
        return
    for dup_id in duplicates:
        update_task(dup_id, status="closed")
        append_work_note(dup_id, "dedup: closed as duplicate title")
        print(f"Closed duplicate: {dup_id}")
    print(f"Closed {len(duplicates)} duplicates.")


def cmd_report(args):
    now = datetime.now()
    since = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    status_stats = status_counts()
    try:
        import subprocess

        log_out = subprocess.check_output(
            ["git", "log", "--oneline", f"--since={since}"],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="replace").strip()
        commits = log_out.splitlines() if log_out else []
    except Exception:
        commits = []

    stuck = []
    for r in list_tasks():
        if str(r.get("status")) != "in_progress":
            continue
        try:
            try:
                upd = datetime.strptime(str(r["updated_at"]), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                upd = datetime.strptime(str(r["updated_at"])[:19], "%Y-%m-%dT%H:%M:%S")
            if (now - upd).total_seconds() > 10800:
                stuck.append({"id": r["id"], "title": r["title"]})
        except Exception:
            pass

    report = {
        "time": now.strftime("%H:%M"),
        "tasks": status_stats,
        "recent_commits": commits[:5],
        "stuck_tasks": stuck,
        "pending_count": status_stats.get("pending", 0),
        "source": "pm_store markdown",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="QuantLearn PM CLI (markdown store)")
    sub = parser.add_subparsers(dest="command")

    p_create = sub.add_parser("create", help="Create a new task markdown")
    p_create.add_argument("type", choices=["story", "bug", "task", "risk"])
    p_create.add_argument("title")
    p_create.add_argument("--desc", default="")
    p_create.add_argument("--status", default=None)
    p_create.add_argument("--priority", default="P1")

    p_update = sub.add_parser("update", help="Update task frontmatter")
    p_update.add_argument("id")
    p_update.add_argument("--status")
    p_update.add_argument("--priority")
    p_update.add_argument("--title")
    p_update.add_argument("--note", help="Append work_notes line")

    p_get = sub.add_parser("get", help="Show one task as JSON")
    p_get.add_argument("id")

    p_list = sub.add_parser("list", help="List tasks")
    p_list.add_argument("--status")
    p_list.add_argument("--type", choices=["story", "bug", "task", "risk"])
    p_list.add_argument("--archive", action="store_true")
    p_list.add_argument("--write-backlog", action="store_true")

    p_timeout = sub.add_parser("timeout", help="Reset stuck in_progress → pending")
    p_timeout.add_argument("--hours", type=int, default=6)

    sub.add_parser("report", help="Hourly PM report JSON")
    sub.add_parser("dedup", help="Close duplicate open/pending titles")
    sub.add_parser("next-id", help="Print next REQ/BUG id")

    args = parser.parse_args()
    if args.command == "create":
        cmd_create(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "get":
        return cmd_get(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "dedup":
        cmd_dedup(args)
    elif args.command == "timeout":
        cmd_timeout_reset(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "next-id":
        print("story", next_id("story"))
        print("bug", next_id("bug"))
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main() or 0)
