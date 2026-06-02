"""REQ-006 快捷操作面板 API tests."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _init_pm_db(path: Path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL,
                priority TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                assigned_to TEXT,
                result_notes TEXT,
                root_cause TEXT,
                fix_commit TEXT,
                work_notes TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO tasks (id,type,title,description,status,priority,created_at,updated_at)
            VALUES ('REQ-006','story','REQ-006: 快捷操作面板','', 'in_progress','P2','2026-06-01 10:00:00','2026-06-01 10:00:00')
            """
        )
        conn.commit()


def test_quick_create_and_status_update(tmp_path):
    from web.app import app

    db_path = tmp_path / "pm.db"
    _init_pm_db(db_path)
    app.config["TESTING"] = True
    app.config["PM_DB_PATH"] = str(db_path)

    with app.test_client() as client:
        res = client.post(
            "/api/pm/tasks",
            json={"type": "story", "title": "新增快捷创建入口", "description": "从面板创建", "priority": "P2"},
        )
        assert res.status_code == 200, res.get_data(as_text=True)
        body = res.get_json()
        assert body["status"] == "ok"
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
    from web.app import app

    db_path = tmp_path / "pm.db"
    _init_pm_db(db_path)
    app.config["TESTING"] = True
    app.config["PM_DB_PATH"] = str(db_path)

    with app.test_client() as client:
        assert client.post("/api/pm/tasks", json={"type": "story", "title": ""}).status_code == 400
        assert client.post("/api/pm/tasks/REQ-006/status", json={"status": "bad"}).status_code == 400
        assert client.post("/api/pm/tasks/REQ-999/status", json={"status": "done"}).status_code == 404
