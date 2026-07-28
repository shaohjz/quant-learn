#!/usr/bin/env python3
"""PM 日报：从 markdown 任务真源汇总（不再读 pm.db）。"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pm_store import list_tasks  # noqa: E402


def bucket(s: str) -> str:
    s = (s or "").lower()
    if s in ("todo", "pending", "open"):
        return "todo"
    if s in ("in_progress", "doing", "progress"):
        return "in_progress"
    if s in ("done", "verified", "fixed", "closed", "deployed"):
        return "done"
    if s in ("blocked", "block"):
        return "blocked"
    return s


def main() -> None:
    tasks = list_tasks()
    buckets: dict[str, list] = defaultdict(list)
    for t in tasks:
        buckets[bucket(str(t.get("status")))].append(t)

    print("=== STATUS DISTRIBUTION (active tasks, n=%d) ===" % len(tasks))
    cnt = Counter(bucket(str(t.get("status"))) for t in tasks)
    for k, v in sorted(cnt.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")

    print("\n=== TODO / PENDING ===")
    for t in buckets["todo"]:
        print(f"  [{t.get('priority')}] {t['id']} - {t.get('title')}  (assigned: {t.get('assigned_to')})")

    print("\n=== IN_PROGRESS ===")
    for t in buckets["in_progress"]:
        print(f"  [{t.get('priority')}] {t['id']} - {t.get('title')}")

    print("\n=== TESTING (needs verify) ===")
    for t in buckets["testing"]:
        print(f"  [{t.get('priority')}] {t['id']} - {t.get('title')}  (updated: {t.get('updated_at')})")

    print("\n=== DONE/VERIFIED ===")
    for t in buckets["done"]:
        print(f"  [{t.get('priority')}] {t['id']} - {t.get('title')}")

    print("\n=== BLOCKED ===")
    for t in buckets["blocked"]:
        print(f"  [{t.get('priority')}] {t['id']} - {t.get('title')}")

    print("\n=== PRIORITY x STATUS MATRIX ===")
    prio_order = ["P0", "high", "P1", "medium", "P2", "P3"]
    matrix: dict = defaultdict(Counter)
    for t in tasks:
        matrix[t.get("priority")][bucket(str(t.get("status")))] += 1
    for p in prio_order:
        if matrix[p]:
            parts = ", ".join(f"{k}={v}" for k, v in matrix[p].items())
            print(f"  {p}: {parts}")


if __name__ == "__main__":
    main()
