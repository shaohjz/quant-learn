#!/usr/bin/env python3
"""Cursor hook: git commit 若改了调度/波段入口却没改 DEPLOYMENT.md → ask。

stdin: beforeShellExecution JSON
stdout: {"permission":"allow"|"ask"|"deny", "user_message":..., "agent_message":...}
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

IMPACT = re.compile(
    r"("
    r"scripts/.*_runner\.bat|"
    r"scripts/swing_pool|"
    r"scripts/swing_daily|"
    r"scripts/swing_intraday|"
    r"scripts/quant_pulse|"
    r"scripts/morning_scanner|"
    r"scripts/intraday_scanner|"
    r"docs/CRON_JOBS\.md|"
    r"docs/REALTIME\.md"
    r")"
)

DEPLOY_DOC = "docs/DEPLOYMENT.md"


def staged_files() -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}

    cmd = str(payload.get("command") or "")
    # 只拦真正的 commit（不含 commit --amend 以外的查询）
    if not re.search(r"\bgit\s+commit\b", cmd):
        print(json.dumps({"permission": "allow"}))
        return 0

    files = staged_files()
    if not files:
        print(json.dumps({"permission": "allow"}))
        return 0

    impact = [f for f in files if IMPACT.search(f)]
    deploy_touched = DEPLOY_DOC in files or any(f.endswith("DEPLOYMENT.md") for f in files)

    if impact and not deploy_touched:
        msg = (
            "本次提交改了调度/波段相关文件，但未改 docs/DEPLOYMENT.md。\n"
            f"影响文件: {', '.join(impact[:8])}"
            + ("…" if len(impact) > 8 else "")
            + "\n请先更新 DEPLOYMENT.md（schtasks / 冒烟 / 口令），再提交；"
            "或确认无需改文档后让用户批准。"
        )
        print(
            json.dumps(
                {
                    "permission": "ask",
                    "user_message": msg,
                    "agent_message": msg
                    + " 同步检查 docs/CRON_JOBS.md / docs/REALTIME.md 是否需要一并更新。",
                },
                ensure_ascii=False,
            )
        )
        return 0

    print(json.dumps({"permission": "allow"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
