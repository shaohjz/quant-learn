#!/usr/bin/env python3
"""PM 活跃任务（markdown）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pm_store import list_tasks  # noqa: E402

print("===== PENDING / OPEN =====")
for r in list_tasks():
    if str(r.get("status")) not in ("pending", "open"):
        continue
    print(f"\n[{r['id']}] type={r.get('type')} prio={r.get('priority')} @={r.get('assigned_to')}")
    print(f"  title: {r.get('title')}")

print("\n\n===== TESTING =====")
for r in list_tasks(status="testing"):
    print(f"\n[{r['id']}] prio={r.get('priority')} upd={r.get('updated_at')}")
    print(f"  title: {r.get('title')}")
