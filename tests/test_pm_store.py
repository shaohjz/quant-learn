"""pm_store markdown frontmatter round-trip."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pm_store as store  # noqa: E402


def test_upsert_get_update(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(store, "REQ_DIR", tmp_path / "pm" / "requirements")
    monkeypatch.setattr(store, "BUG_DIR", tmp_path / "pm" / "bugs")
    monkeypatch.setattr(store, "ARCHIVE_DIR", tmp_path / "pm" / "archive")
    monkeypatch.setattr(store, "BACKLOG_PATH", tmp_path / "pm" / "BACKLOG.md")

    t = store.upsert_task(
        type="bug",
        title="测试串价",
        description="desc",
        status="open",
        priority="P0",
    )
    assert t["id"].startswith("BUG-")
    path = tmp_path / t["path"]
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "id:" in text

    got = store.get_task(t["id"])
    assert got is not None
    assert got["title"] == "测试串价"
    assert got["priority"] == "P0"

    store.update_task(t["id"], status="verified")
    got2 = store.get_task(t["id"])
    assert got2["status"] == "verified"

    rows = store.list_tasks(status="verified")
    assert any(r["id"] == t["id"] for r in rows)


def test_parse_dump_roundtrip():
    meta = {"id": "REQ-999", "type": "story", "title": "x", "status": "open", "priority": "P1"}
    body = "# hello\n\nworld\n"
    text = store.dump_frontmatter(meta, body)
    m2, b2 = store.parse_frontmatter(text)
    assert m2["id"] == "REQ-999"
    assert "hello" in b2


def test_skip_legacy_md_without_frontmatter(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(store, "REQ_DIR", tmp_path / "pm" / "requirements")
    monkeypatch.setattr(store, "BUG_DIR", tmp_path / "pm" / "bugs")
    monkeypatch.setattr(store, "ARCHIVE_DIR", tmp_path / "pm" / "archive")
    store.ensure_dirs()
    legacy = store.BUG_DIR / "BUG-001-old.md"
    legacy.write_text("# old bug\n\nno frontmatter\n", encoding="utf-8")
    store.upsert_task(id="REQ-001", type="story", title="real", status="open", priority="P1")
    ids = {t["id"] for t in store.list_tasks()}
    assert "REQ-001" in ids
    assert "BUG-001-old" not in ids
