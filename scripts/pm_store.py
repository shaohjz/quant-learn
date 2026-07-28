#!/usr/bin/env python3
"""PM 任务真源：pm/requirements + pm/bugs（+ pm/archive）Markdown + YAML frontmatter。

不再使用 data/pm.db 的 tasks 表。Cursor / OpenClaw / Web / 日报统一走本模块。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
REQ_DIR = ROOT / "pm" / "requirements"
BUG_DIR = ROOT / "pm" / "bugs"
ARCHIVE_DIR = ROOT / "pm" / "archive"
BACKLOG_PATH = ROOT / "pm" / "BACKLOG.md"

META_KEYS = (
    "id",
    "type",
    "title",
    "status",
    "priority",
    "created_at",
    "updated_at",
    "assigned_to",
    "result_notes",
    "root_cause",
    "fix_commit",
    "work_notes",
    "description",
)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_dirs() -> None:
    REQ_DIR.mkdir(parents=True, exist_ok=True)
    BUG_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (meta, body). If no frontmatter, meta={} and body=text."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw, body = m.group(1), m.group(2)
    try:
        meta = yaml.safe_load(raw) or {}
    except Exception:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, body


def dump_frontmatter(meta: dict[str, Any], body: str) -> str:
    clean = {k: meta[k] for k in META_KEYS if k in meta and meta[k] is not None}
    # keep unknown keys too
    for k, v in meta.items():
        if k not in clean and v is not None:
            clean[k] = v
    fm = yaml.safe_dump(clean, allow_unicode=True, sort_keys=False, default_flow_style=False)
    body = body or ""
    if body and not body.startswith("\n"):
        return f"---\n{fm}---\n\n{body.lstrip()}"
    return f"---\n{fm}---\n{body}"


def _dir_for_type(task_type: str, *, archived: bool = False) -> Path:
    if archived:
        return ARCHIVE_DIR
    t = (task_type or "").lower()
    if t in ("bug", "risk"):
        return BUG_DIR
    return REQ_DIR


def _guess_id_from_path(path: Path) -> str:
    stem = path.stem
    # REQ-061-daily-return-null → REQ-061
    m = re.match(r"^(REQ-\d+|BUG-[\w-]+|TASK-[\w-]+)", stem, re.I)
    if m:
        return m.group(1)
    return stem


def _scan_files(*, include_archive: bool = False) -> list[Path]:
    ensure_dirs()
    paths: list[Path] = []
    for d in (REQ_DIR, BUG_DIR):
        paths.extend(sorted(d.glob("*.md")))
    if include_archive:
        paths.extend(sorted(ARCHIVE_DIR.glob("*.md")))
    return paths


def path_for_task(task_id: str, task_type: str | None = None, *, archived: bool = False) -> Path | None:
    """Find existing file for id, or propose path if creating."""
    tid = str(task_id).strip()
    for p in _scan_files(include_archive=True):
        meta, _ = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
        mid = str(meta.get("id") or _guess_id_from_path(p))
        if mid == tid or p.stem == tid or p.stem.startswith(tid + "-"):
            return p
    if task_type is None:
        if tid.upper().startswith("BUG"):
            task_type = "bug"
        elif tid.upper().startswith("TASK"):
            task_type = "task"
        else:
            task_type = "story"
    return _dir_for_type(task_type, archived=archived) / f"{tid}.md"


def load_task(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta, body = parse_frontmatter(text)
    tid = str(meta.get("id") or _guess_id_from_path(path))
    task = {k: meta.get(k) for k in META_KEYS}
    task["id"] = tid
    task["type"] = task.get("type") or (
        "bug" if tid.upper().startswith("BUG") else "task" if tid.upper().startswith("TASK") else "story"
    )
    task["title"] = task.get("title") or tid
    task["status"] = task.get("status") or "open"
    task["priority"] = task.get("priority") or "P2"
    task["description"] = task.get("description") or ""
    task["body"] = body
    task["path"] = str(path.relative_to(ROOT)).replace("\\", "/")
    # legacy markdown without frontmatter: pull title from first heading
    if (not meta.get("title")) and body:
        hm = re.search(r"^#\s+(.+)$", body, re.M)
        if hm:
            task["title"] = hm.group(1).strip()
    return task


def list_tasks(
    *,
    status: str | None = None,
    type: str | None = None,
    priority: str | None = None,
    include_archive: bool = False,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in _scan_files(include_archive=include_archive):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            meta, _ = parse_frontmatter(text)
            # 无 YAML frontmatter 的历史文档不进任务队列（仍可人工阅读）
            if "id" not in meta:
                continue
            t = load_task(p)
        except Exception:
            continue
        tid = t["id"]
        if tid in seen:
            continue
        seen.add(tid)
        if status and str(t.get("status")) != status:
            continue
        if type and str(t.get("type")) != type:
            continue
        if priority and str(t.get("priority")) != priority:
            continue
        tasks.append(t)

    def _prio_key(p: str) -> int:
        order = {"P0": 0, "high": 1, "P1": 2, "medium": 3, "P2": 4, "P3": 5, "low": 6}
        return order.get(str(p), 9)

    tasks.sort(key=lambda t: (_prio_key(t.get("priority") or ""), str(t.get("updated_at") or ""), t["id"]))
    return tasks


def get_task(task_id: str) -> dict[str, Any] | None:
    p = path_for_task(task_id)
    if p is None or not p.exists():
        # try linear scan
        for t in list_tasks(include_archive=True):
            if t["id"] == task_id:
                return t
        return None
    return load_task(p)


def next_id(task_type: str) -> str:
    """REQ-NNN / BUG-NNN based on max numeric suffix among REQ-/BUG- ids."""
    prefix = "REQ-" if task_type == "story" else "BUG-"
    max_num = 0
    for t in list_tasks(include_archive=True):
        tid = str(t["id"])
        if not tid.startswith(prefix):
            continue
        # BUG-20260624-001 → skip date-style; only NNN
        rest = tid[len(prefix) :]
        if re.fullmatch(r"\d{1,4}", rest):
            max_num = max(max_num, int(rest))
    return f"{prefix}{max_num + 1:03d}"


def upsert_task(
    *,
    id: str | None = None,
    type: str = "story",
    title: str,
    description: str = "",
    status: str | None = None,
    priority: str = "P1",
    assigned_to: str | None = None,
    result_notes: str | None = None,
    root_cause: str | None = None,
    fix_commit: str | None = None,
    work_notes: str | None = None,
    body: str | None = None,
    merge_body: bool = True,
) -> dict[str, Any]:
    ensure_dirs()
    now = _now()
    task_id = id or next_id(type)
    existing_path = None
    existing: dict[str, Any] | None = None
    for t in list_tasks(include_archive=True):
        if t["id"] == task_id:
            existing = t
            existing_path = ROOT / t["path"]
            break

    if status is None:
        status = "pending" if type == "story" else "open"

    meta: dict[str, Any] = {
        "id": task_id,
        "type": type,
        "title": title,
        "status": status,
        "priority": priority,
        "created_at": (existing or {}).get("created_at") or now,
        "updated_at": now,
    }
    if assigned_to is not None:
        meta["assigned_to"] = assigned_to
    elif existing and existing.get("assigned_to"):
        meta["assigned_to"] = existing["assigned_to"]
    for k, v in (
        ("result_notes", result_notes),
        ("root_cause", root_cause),
        ("fix_commit", fix_commit),
        ("work_notes", work_notes),
        ("description", description),
    ):
        if v is not None:
            meta[k] = v
        elif existing and existing.get(k):
            meta[k] = existing[k]

    if body is not None:
        new_body = body
    elif existing and merge_body:
        new_body = existing.get("body") or ""
        if description and description not in new_body and not existing.get("description"):
            new_body = (new_body + f"\n\n## 描述\n\n{description}\n").lstrip()
    else:
        new_body = f"# {title}\n\n## 描述\n\n{description or '（待补充）'}\n"

    out_path = existing_path or (_dir_for_type(type) / f"{task_id}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(dump_frontmatter(meta, new_body), encoding="utf-8")
    return load_task(out_path)


def update_task(task_id: str, **fields: Any) -> dict[str, Any] | None:
    t = get_task(task_id)
    if not t:
        return None
    allowed = {
        "title",
        "status",
        "priority",
        "type",
        "description",
        "assigned_to",
        "result_notes",
        "root_cause",
        "fix_commit",
        "work_notes",
        "body",
    }
    kwargs = {k: fields[k] for k in allowed if k in fields and fields[k] is not None}
    return upsert_task(
        id=task_id,
        type=kwargs.get("type") or t.get("type") or "story",
        title=kwargs.get("title") or t.get("title") or task_id,
        description=kwargs.get("description") if "description" in kwargs else (t.get("description") or ""),
        status=kwargs.get("status") or t.get("status"),
        priority=kwargs.get("priority") or t.get("priority") or "P1",
        assigned_to=kwargs.get("assigned_to") if "assigned_to" in kwargs else t.get("assigned_to"),
        result_notes=kwargs.get("result_notes") if "result_notes" in kwargs else t.get("result_notes"),
        root_cause=kwargs.get("root_cause") if "root_cause" in kwargs else t.get("root_cause"),
        fix_commit=kwargs.get("fix_commit") if "fix_commit" in kwargs else t.get("fix_commit"),
        work_notes=kwargs.get("work_notes") if "work_notes" in kwargs else t.get("work_notes"),
        body=kwargs.get("body") if "body" in kwargs else None,
        merge_body=True,
    )


def append_work_note(task_id: str, note: str) -> dict[str, Any] | None:
    t = get_task(task_id)
    if not t:
        return None
    stamp = _now()
    line = f"[{stamp}] {note.strip()}"
    prev = (t.get("work_notes") or "").rstrip()
    new_notes = f"{prev}\n{line}".strip() if prev else line
    return update_task(task_id, work_notes=new_notes)


def write_backlog(path: Path | None = None) -> Path:
    """Generate pm/BACKLOG.md summary from frontmatter."""
    out = path or BACKLOG_PATH
    tasks = list_tasks(include_archive=False)
    lines = [
        "# PM Backlog",
        "",
        f"> 自动生成于 {_now()}（`pm_cli list --write-backlog`）。真源为各 REQ/BUG markdown。",
        "",
        "| ID | 类型 | 状态 | 优先级 | 标题 |",
        "|----|------|------|--------|------|",
    ]
    for t in tasks:
        title = str(t.get("title") or "").replace("|", "/")
        lines.append(
            f"| {t['id']} | {t.get('type')} | {t.get('status')} | {t.get('priority')} | {title} |"
        )
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def status_counts(*, include_archive: bool = False) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in list_tasks(include_archive=include_archive):
        s = str(t.get("status") or "unknown")
        counts[s] = counts.get(s, 0) + 1
    return counts
