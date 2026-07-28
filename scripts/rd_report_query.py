#!/usr/bin/env python3
"""研发经理日报查询 — 任务来自 markdown；行情仍读 sim_live_mirror.db。"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pm_store import list_tasks, status_counts  # noqa: E402

print("=== PM Task Status Summary (markdown) ===")
for k, v in sorted(status_counts().items(), key=lambda x: -x[1]):
    print(f"  {k:15s} : {v}")

print("\n=== PM Task Type Summary ===")
from collections import Counter

types = Counter(t.get("type") for t in list_tasks())
for k, v in types.items():
    print(f"  {str(k):15s} : {v}")

print("\n=== Recent PM Tasks (by updated_at) ===")
rows = sorted(list_tasks(), key=lambda t: str(t.get("updated_at") or ""), reverse=True)[:20]
for r in rows:
    title = (r.get("title") or "")[:70]
    print(
        f"  {r['id']:20s} | {r.get('type')!s:6s} | {r.get('status')!s:12s} | "
        f"{r.get('priority')!s:3s} | {title} | {r.get('updated_at')}"
    )

print("\n=== Tasks in_progress ===")
for r in list_tasks(status="in_progress"):
    print(f"  {r['id']} | {r.get('priority')} | {r.get('assigned_to') or 'unassigned':20s} | {(r.get('title') or '')[:60]}")

print("\n=== Open Bugs ===")
for r in list_tasks(type="bug"):
    if str(r.get("status")) in ("fixed", "verified", "closed", "deployed"):
        continue
    print(f"  {r['id']} | {r.get('priority')} | {r.get('status')} | {(r.get('title') or '')[:70]} | {r.get('updated_at')}")

sim_db = ROOT / "data" / "sim_live_mirror.db"
if sim_db.exists():
    conn2 = sqlite3.connect(str(sim_db))
    conn2.row_factory = sqlite3.Row
    print("\n=== Sim Positions ===")
    for p in conn2.execute(
        "SELECT account_id, COUNT(*) as cnt, SUM(market_value) as mv FROM sim_positions "
        "WHERE quantity>0 GROUP BY account_id"
    ):
        print(f"  account_id={p['account_id']}: {p['cnt']} positions, MV={round(p['mv'] or 0, 2)}")
    print("\n=== Recent NAV (last 10) ===")
    for n in conn2.execute(
        "SELECT trade_date, account_id, total_value, cumulative_return FROM sim_daily_nav "
        "ORDER BY trade_date DESC LIMIT 10"
    ):
        ret = round((n["cumulative_return"] or 0) * 100, 2)
        print(f"  {n['trade_date']} | acct={n['account_id']} | value={round(n['total_value'],2)} | ret={ret}%")
    conn2.close()
else:
    print("\n(sim_live_mirror.db missing)")

reports_dir = ROOT / "daily_reports"
print(f"\n=== Daily Reports Dir: {reports_dir} ===")
if reports_dir.is_dir():
    for f in sorted(os.listdir(reports_dir), reverse=True)[:5]:
        print(f"  {f}")
print("\nDone.")
