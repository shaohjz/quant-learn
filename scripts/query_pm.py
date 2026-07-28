#!/usr/bin/env python3
"""查询 PM 任务（markdown）。兼容旧脚本名 query_pm.py。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pm_store import list_tasks  # noqa: E402

print("=== TASKS (markdown) ===")
for t in sorted(list_tasks(), key=lambda x: str(x.get("updated_at") or ""), reverse=True):
    print(
        f"{t['id']:24s} {t.get('type')!s:6s} {t.get('status')!s:12s} "
        f"{t.get('priority')!s:8s} {(t.get('title') or '')[:60]}"
    )
