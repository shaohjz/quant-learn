"""
scripts/pm_agent_push.py — 由 pm_agent_hourly.bat 调用
读取 stdinput（pm_cli.py report 的 JSON 输出），判断是否需要推送企微
"""
from __future__ import annotations
import sys, json, os, subprocess

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print("NO_REPLY")
        return
    try:
        data = json.loads(raw)
    except Exception:
        print(f"PARSE_ERROR: {raw[:200]}")
        return

    should_notify = (
        len(data.get("stuck_tasks", [])) > 0
        or data.get("pending_count", 0) > 15
        or len(data.get("recent_commits", [])) > 0
    )

    if not should_notify:
        print("NO_REPLY  (no change)")
        return

    # 格式化推送
    lines = []
    t = data.get("time", "--:--")
    lines.append(f"📊 PM 汇报 · {t}")
    tasks = data.get("tasks", {})
    lines.append(f"📊 任务：{tasks.get('done',0)} done / {tasks.get('testing',0)} testing / {tasks.get('in_progress',0)} in_progress / {tasks.get('pending',0)} pending")

    if data.get("recent_commits"):
        lines.append(f"📊 最近 1h commit：{len(data['recent_commits'])} 条")
    if data.get("stuck_tasks"):
        lines.append(f"⚠️ 阻塞项：{len(data['stuck_tasks'])} 个任务超时")

    msg = chr(10).join(lines)

    # 用 openclaw message tool 推送（通过 CLI）
    # 让 main session 处理：写文件，main session 的 heartbeat 会读
    flag = os.path.join(os.environ.get("USERPROFILE", "C:\\"), ".openclaw", "pm_push_flag.txt")
    with open(flag, "w", encoding="utf-8") as f:
        f.write(msg)
    print(f"PUSH_OK: written to {flag}")

if __name__ == "__main__":
    main()
