#!/usr/bin/env python3
"""废弃：原 dump 整个 pm.db。现打印 markdown 任务摘要。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pm_store import list_tasks, status_counts  # noqa: E402

print("NOTE: pm.db tasks retired. Source = pm/requirements + pm/bugs markdown.")
print("STATUS:", status_counts())
print("COUNT:", len(list_tasks()))
for t in list_tasks():
    print(t["id"], t.get("status"), t.get("priority"), t.get("title"))
