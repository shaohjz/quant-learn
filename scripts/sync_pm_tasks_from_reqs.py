"""Sync data/pm.db tasks table status with pm/requirements/*.md verified status.

Root cause: PM agent closed REQs (status=verified) directly in the .md docs on
2026-08-21 01:17, but never wrote the closure back to data/pm.db `tasks` table.
The daily PM report then read the stale tasks table and wrongly reported
"5 P2 stories + 2 P1 tech-debt stalled 11 days".

This script reconciles task.status from the authoritative REQ doc status.
Mapping (REQ doc status -> task status):
  verified / deployed / closed / done -> done
  testing -> in_progress (still needs production verification, do NOT mark done)
  todo / pending -> todo (leave)
"""
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "pm.db"
REQ_DIR = ROOT / "pm" / "requirements"

# REQ id -> doc status, parsed from front-matter `status:` line
def read_req_statuses():
    out = {}
    for f in REQ_DIR.glob("REQ-*.md"):
        m = re.match(r"REQ-(\d+)", f.name)
        if not m:
            continue
        req_id = f"REQ-{m.group(1)}"
        text = f.read_text(encoding="utf-8")
        fm = text.split("---", 2)
        if len(fm) < 2:
            continue
        s = re.search(r'^status:\s*(\S+)', fm[1], re.MULTILINE)
        if s:
            out[req_id] = s.group(1).strip()
    return out

# Task id -> REQ id (from desc field, e.g. "REQ-020 [story]")
def task_req_id(desc):
    m = re.search(r"(REQ-\d+)", desc or "")
    return m.group(1) if m else None

def map_status(doc_status):
    done = {"verified", "deployed", "closed", "done"}
    prog = {"testing", "in_progress", "in-progress"}
    if doc_status in done:
        return "done"
    if doc_status in prog:
        return "in_progress"
    return "todo"

def main():
    req_statuses = read_req_statuses()
    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()
    rows = cur.execute("SELECT id, title, desc, status FROM tasks").fetchall()

    changes = []
    for tid, title, desc, cur_status in rows:
        rid = task_req_id(desc)
        if not rid or rid not in req_statuses:
            continue
        doc_status = req_statuses[rid]
        new_status = map_status(doc_status)
        if new_status != cur_status:
            changes.append((tid, title, rid, cur_status, doc_status, new_status))

    # apply
    for tid, title, rid, old, doc, new in changes:
        cur.execute(
            "UPDATE tasks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (new, tid),
        )
    conn.commit()

    print(f"Doc statuses found: {len(req_statuses)}")
    print(f"Task changes applied: {len(changes)}")
    for c in changes:
        tid, title, rid, old, doc, new = c
        print(f"  #{tid} [{rid}] {old} -> {new} (doc={doc})  | {title[:40]}")

    # final distribution
    dist = cur.execute(
        "SELECT status, COUNT(*) FROM tasks GROUP BY status ORDER BY status"
    ).fetchall()
    print("\nFinal distribution:", dict(dist))
    conn.close()

if __name__ == "__main__":
    main()
