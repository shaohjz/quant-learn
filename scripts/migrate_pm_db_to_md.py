#!/usr/bin/env python3
"""一次性：data/pm.db tasks → pm/requirements|bugs|archive Markdown。

已有同名 md：合并 frontmatter，不覆盖已有长正文。
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pm_store import (  # noqa: E402
    ARCHIVE_DIR,
    BUG_DIR,
    REQ_DIR,
    dump_frontmatter,
    ensure_dirs,
    get_task,
    parse_frontmatter,
    path_for_task,
)

DB_DEFAULT = ROOT / "data" / "pm.db"


def _safe_filename(task_id: str, title: str = "") -> str:
    tid = re.sub(r"[^\w\-]", "-", task_id)
    return f"{tid}.md"


def _row_to_meta(row: sqlite3.Row) -> dict:
    keys = row.keys()
    meta = {
        "id": row["id"],
        "type": row["type"] if "type" in keys else "story",
        "title": row["title"] if "title" in keys else row["id"],
        "status": row["status"] if "status" in keys else "open",
        "priority": row["priority"] if "priority" in keys else "P2",
        "created_at": row["created_at"] if "created_at" in keys else "",
        "updated_at": row["updated_at"] if "updated_at" in keys else "",
    }
    for k in ("assigned_to", "result_notes", "root_cause", "fix_commit", "work_notes", "description"):
        if k in keys and row[k]:
            meta[k] = row[k]
    return meta


def _default_body(meta: dict) -> str:
    parts = [f"# {meta.get('title') or meta['id']}", ""]
    desc = meta.get("description") or ""
    if desc:
        parts += ["## 描述", "", desc, ""]
    if meta.get("root_cause"):
        parts += ["## 根因", "", str(meta["root_cause"]), ""]
    if meta.get("result_notes"):
        parts += ["## 修复备注", "", str(meta["result_notes"]), ""]
    if meta.get("work_notes"):
        parts += ["## 工作日志", "", "```", str(meta["work_notes"]), "```", ""]
    return "\n".join(parts)


def _migrate_rows(rows: list[sqlite3.Row], *, archived: bool) -> tuple[int, int]:
    created = updated = 0
    for row in rows:
        meta = _row_to_meta(row)
        tid = meta["id"]
        existing = get_task(tid)
        if existing and not archived:
            # merge: prefer DB status/priority/notes onto existing file; keep body
            path = ROOT / existing["path"]
            text = path.read_text(encoding="utf-8", errors="replace")
            old_meta, body = parse_frontmatter(text)
            if not body.strip():
                body = existing.get("body") or _default_body(meta)
            merged = {**old_meta, **{k: v for k, v in meta.items() if v}}
            # keep richer title from md if longer
            if old_meta.get("title") and len(str(old_meta["title"])) > len(str(merged.get("title") or "")):
                merged["title"] = old_meta["title"]
            path.write_text(dump_frontmatter(merged, body), encoding="utf-8")
            updated += 1
            continue

        ttype = meta.get("type") or "story"
        if archived:
            out = ARCHIVE_DIR / _safe_filename(tid)
        else:
            proposed = path_for_task(tid, ttype, archived=False)
            out = proposed if proposed else (BUG_DIR if ttype == "bug" else REQ_DIR) / _safe_filename(tid)
            # if a differently named file already exists for this id, use it
            if existing:
                out = ROOT / existing["path"]

        if out.exists() and archived:
            # skip overwrite archive if present
            updated += 1
            continue

        body = _default_body(meta)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(dump_frontmatter(meta, body), encoding="utf-8")
        created += 1
    return created, updated


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate pm.db tasks → markdown")
    ap.add_argument("--db", type=Path, default=DB_DEFAULT)
    ap.add_argument("--skip-archive", action="store_true")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 2

    ensure_dirs()
    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row

    tasks = conn.execute("SELECT * FROM tasks").fetchall()
    c1, u1 = _migrate_rows(tasks, archived=False)
    print(f"tasks: created={c1} updated={u1} total={len(tasks)}")

    if not args.skip_archive:
        try:
            arch = conn.execute("SELECT * FROM tasks_archive").fetchall()
        except sqlite3.OperationalError:
            arch = []
        c2, u2 = _migrate_rows(arch, archived=True)
        print(f"archive: created={c2} skipped/updated={u2} total={len(arch)}")

    conn.close()
    print("Done. Review pm/requirements, pm/bugs, pm/archive.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
