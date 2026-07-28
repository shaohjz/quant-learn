"""REQ-006 快捷操作面板 API tests（markdown PM 真源）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _seed(tmp_path: Path):
    import pm_store as store

    store.ROOT = tmp_path
    store.REQ_DIR = tmp_path / "pm" / "requirements"
    store.BUG_DIR = tmp_path / "pm" / "bugs"
    store.ARCHIVE_DIR = tmp_path / "pm" / "archive"
    store.ensure_dirs()
    store.upsert_task(
        id="REQ-006",
        type="story",
        title="REQ-006: 快捷操作面板",
        status="in_progress",
        priority="P2",
    )


def test_quick_create_and_status_update(tmp_path):
    pytest.importorskip("flask")
    from web.app import app

    _seed(tmp_path)
    app.config["TESTING"] = True
    app.config["PM_ROOT"] = str(tmp_path)

    with app.test_client() as client:
        res = client.post(
            "/api/pm/tasks",
            json={
                "type": "story",
                "title": "新增快捷创建入口",
                "description": "从面板创建",
                "priority": "P2",
            },
        )
        assert res.status_code == 200, res.get_data(as_text=True)
        body = res.get_json()
        assert body["status"] == "ok"
        # next after REQ-006
        assert body["task"]["id"] == "REQ-007"
        assert body["task"]["status"] == "pending"

        res = client.post(
            "/api/pm/tasks/REQ-007/status",
            json={"status": "done", "note": "快捷操作完成"},
        )
        assert res.status_code == 200, res.get_data(as_text=True)
        assert res.get_json()["task"]["status"] == "done"

        res = client.get("/api/pm_tasks")
        assert res.status_code == 200
        tasks = {t["id"]: t for t in res.get_json()["tasks"]}
        assert tasks["REQ-007"]["status"] == "done"
        assert "快捷操作完成" in (tasks["REQ-007"].get("work_notes") or "")


def test_quick_action_validation(tmp_path):
    pytest.importorskip("flask")
    from web.app import app

    _seed(tmp_path)
    app.config["TESTING"] = True
    app.config["PM_ROOT"] = str(tmp_path)

    with app.test_client() as client:
        assert client.post("/api/pm/tasks", json={"type": "story", "title": ""}).status_code == 400
        assert client.post("/api/pm/tasks/REQ-006/status", json={"status": "bad"}).status_code == 400
        assert client.post("/api/pm/tasks/REQ-999/status", json={"status": "done"}).status_code == 404
