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
import requests
from pathlib import Path

# ── 读 config.yaml 的 notify.wecom_webhook ───────────────────────
ROOT = Path(__file__).resolve().parents[1]


def _load_webhook() -> str:
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
        return (cfg.get("notify") or {}).get("wecom_webhook", "") or ""
    except Exception:
        return ""


def push_text(content: str) -> bool:
    """纯代码推文本到企微群机器人，无需大模型"""
    url = _load_webhook()
    if not url:
        print("[pm_agent_push] ⚠️ 未配置 notify.wecom_webhook，跳过推送", file=sys.stderr)
        return False
    try:
        r = requests.post(
            url,
            json={"msgtype": "text", "text": {"content": content}},
            timeout=8,
        )
        ok = r.ok and r.json().get("errcode") == 0
        print(f"[pm_agent_push] {'✅ 推送成功' if ok else '⚠️ 推送失败：' + r.text[:120]}")
        return ok
    except Exception as e:
        print(f"[pm_agent_push] ⚠️ 推送异常：{e}", file=sys.stderr)
        return False


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
    print(msg)

    # REQ-042 去大模型化：直接 Webhook 直推，无需 Agent 中转
    ok = push_text(msg)
    print(f"PUSH_OK: webhook={'success' if ok else 'failed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
