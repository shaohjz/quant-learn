#!/usr/bin/env python3
"""PM 状态一览（markdown 真源）。"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pm_store import list_tasks  # noqa: E402


def main() -> None:
    rows = list_tasks()
    print("=== ACTIVE TASK COUNT:", len(rows), "===")
    print("STATUS BREAKDOWN:", dict(Counter(r.get("status") for r in rows)))
    print("PRIORITY BREAKDOWN:", dict(Counter(r.get("priority") for r in rows)))
    print("\n=== DETAIL ===")
    for r in rows:
        print(f"\n[{r['id']}] {r.get('title')}")
        print(
            f"  status={r.get('status')} | priority={r.get('priority')} | "
            f"owner={r.get('assigned_to')} | updated={r.get('updated_at')}"
        )
        if r.get("result_notes"):
            print(f"  result_notes: {str(r['result_notes'])[:200]}")
        if r.get("root_cause"):
            print(f"  root_cause: {str(r['root_cause'])[:200]}")
        if r.get("work_notes"):
            print(f"  work_notes: {str(r['work_notes'])[-300:]}")


if __name__ == "__main__":
    main()
