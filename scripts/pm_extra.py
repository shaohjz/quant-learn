#!/usr/bin/env python3
"""废弃：原 pm.db 额外统计。现打印 markdown 矩阵。"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pm_store import list_tasks  # noqa: E402

tasks = list_tasks()
print("status x priority:")
c = Counter((t.get("status"), t.get("priority")) for t in tasks)
for k, v in sorted(c.items()):
    print(k, v)
print("assigned_to:")
for k, v in Counter(t.get("assigned_to") or "(none)" for t in tasks).most_common():
    print(k, v)
