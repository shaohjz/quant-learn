"""
scripts/pm_agent_push.py — PM 状态变更推送（纯代码 Webhook 直推）

读取 stdin（pm_cli.py report 的 JSON 输出），判断是否需要推送企微，
直接用 requests 调 Webhook，不再依赖 OpenClaw main session / 大模型中转。

用法（Windows 计划任务 / cron 调用）：
  python scripts/pm_cli.py report | python scripts/pm_agent_push.py
"""

from __future__ import annotations
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.notifier import send_text


def push_text(content: str) -> bool:
    """纯代码推文本到统一企微群机器人，无需大模型。"""
    return send_text(content)


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print("NO_REPLY (empty stdin)")
        return 0

    try:
        data = json.loads(raw)
    except Exception:
        print(f"PARSE_ERROR: {raw[:200]}", file=sys.stderr)
        return 1

    should_notify = (
        len(data.get("stuck_tasks", [])) > 0
        or data.get("pending_count", 0) > 15
        or len(data.get("recent_commits", [])) > 0
    )

    if not should_notify:
        print("NO_REPLY (no change)")
        return 0

    # 格式化推送内容
    lines = []
    t = data.get("time", "--:--")
    lines.append(f"📊 PM 汇报 · {t}")
    tasks = data.get("tasks", {})
    lines.append(
        f"📊 任务：{tasks.get('done',0)} done / "
        f"{tasks.get('testing',0)} testing / "
        f"{tasks.get('in_progress',0)} in_progress / "
        f"{tasks.get('pending',0)} pending"
    )

    if data.get("recent_commits"):
        lines.append(f"📊 最近 1h commit：{len(data['recent_commits'])} 条")
    if data.get("stuck_tasks"):
        lines.append(f"⚠️ 阻塞项：{len(data['stuck_tasks'])} 个任务超时")

    msg = "\n".join(lines)

    # REQ-042 去大模型化：直接 Webhook 直推，无需 Agent 中转
    ok = push_text(msg)
    print(f"PUSH_OK: webhook={'success' if ok else 'failed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
