#!/usr/bin/env python3
"""每日治理产物同步到 origin/master（交易脚本产物 + PM/QA/Ops 落盘）。

设计原则（对齐 docs/DEPLOYMENT.md / REVIEW_LOOP.md）：
- 只提交白名单路径：台账、cursor_queue、REQ/BUG、PLAN、测试报告、ops、波段日报、LLM 各类日报
- 禁止提交：交易核心代码、config.local、*.db、.venv、密钥
- 无变更则静默退出 0；有变更则 commit + push
- 不做 force push；不改 git config
- 建议 schtasks：18:45（台账主班）+ 20:30（承接 20:00 LLM 日报）

用法（产机）：
  .venv\\Scripts\\python.exe -u scripts\\daily_git_sync.py
  .venv\\Scripts\\python.exe -u scripts\\daily_git_sync.py --dry-run
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 允许入库的相对路径前缀 / 精确文件
ALLOW_PREFIXES = (
    "pm/trade_journal/",
    "pm/cursor_queue/",
    "pm/requirements/",
    "pm/bugs/",
    "pm/dev/",
    "pm/test_reports/",
    "pm/ops/",
    "pm/agents/",
    "output/swing_daily/",
    "output/swing_pool/",
    "output/reviews/",
    "output/finance_manager/",
    "daily_reports/",
    "docs/reviews/",  # 理财师脚本历史路径；新日报优先 daily_reports/
)

ALLOW_EXACT = {
    "docs/ROADMAP.md",
    "docs/CRON_JOBS.md",
    "docs/REVIEW_LOOP.md",
    "CRON_JOBS.md",
}

# 绝对禁止（即使误出现在 status 里也不加）
DENY_SUFFIXES = (
    ".db",
    ".db-journal",
    ".env",
    "config.local.yaml",
)
DENY_PREFIXES = (
    "scripts/",
    "vqlearn/",
    "quant_core/",
    "broker/",
    "strategies/",
    "sim/",
    "web/",
    "tests/",
    ".venv/",
    "data/",
)


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def _is_allowed(path: str) -> bool:
    p = path.replace("\\", "/").lstrip("./")
    if any(p.endswith(s) or s in p for s in DENY_SUFFIXES):
        return False
    if any(p.startswith(d) for d in DENY_PREFIXES):
        # allow only exact docs we listed; scripts/ always deny for this sync
        return False
    if p in ALLOW_EXACT:
        return True
    if any(p.startswith(pref) for pref in ALLOW_PREFIXES):
        return True
    # dated daily close / PM 日报 sitting in output/
    if p.startswith("output/daily_close_") and p.endswith(".md"):
        return True
    if p.startswith("output/pm_daily_report_") and p.endswith(".md"):
        return True
    return False


def _changed_paths() -> list[str]:
    """Return porcelain paths (modified + untracked) under allowlist."""
    out = _run(["git", "status", "--porcelain", "-u"], check=True).stdout
    paths: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        # formats: " M path", "?? path", "R  old -> new"
        raw = line[3:] if len(line) > 3 else line
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        path = raw.strip().strip('"')
        if _is_allowed(path):
            paths.append(path)
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync daily PM/trade artifacts to origin/master")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要提交的文件")
    parser.add_argument("--no-push", action="store_true", help="只 commit 不 push")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="master")
    args = parser.parse_args()

    # safety: must be on target branch
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if branch != args.branch:
        print(f"[daily_git_sync] 当前分支={branch}，期望={args.branch}，退出不提交", file=sys.stderr)
        return 2

    paths = _changed_paths()
    if not paths:
        print("[daily_git_sync] 无白名单变更，跳过")
        return 0

    print("[daily_git_sync] 将同步:")
    for p in paths:
        print(f"  - {p}")

    if args.dry_run:
        return 0

    _run(["git", "add", "--"] + paths, check=True)
    # re-check staged
    staged = _run(["git", "diff", "--cached", "--name-only"]).stdout.strip()
    if not staged:
        print("[daily_git_sync] add 后无 staged（可能被 .gitignore），跳过")
        return 0

    day = datetime.now().strftime("%Y-%m-%d")
    has_llm_report = any(
        p.startswith("daily_reports/")
        or p.startswith("docs/reviews/")
        or p.startswith("output/reviews/")
        or p.startswith("output/finance_manager/")
        or p.startswith("output/pm_daily_report_")
        for p in paths
    )
    msg = (
        f"chore(daily): {day} 台账/LLM日报/PM 落盘"
        if has_llm_report
        else f"chore(daily): {day} 交易台账/PM队列/测试与运维落盘"
    )
    # HEREDOC-style via -m is fine for non-interactive
    _run(["git", "commit", "-m", msg], check=True)
    print(f"[daily_git_sync] committed: {msg}")

    if args.no_push:
        print("[daily_git_sync] --no-push，结束")
        return 0

    # pull --rebase first to reduce non-ff failures on shared master
    pull = _run(["git", "pull", "--rebase", args.remote, args.branch], check=False)
    if pull.returncode != 0:
        print(pull.stdout)
        print(pull.stderr, file=sys.stderr)
        print("[daily_git_sync] pull --rebase 失败，未 push", file=sys.stderr)
        return pull.returncode

    push = _run(["git", "push", args.remote, f"HEAD:{args.branch}"], check=False)
    print(push.stdout)
    if push.returncode != 0:
        print(push.stderr, file=sys.stderr)
        print("[daily_git_sync] push 失败", file=sys.stderr)
        return push.returncode

    print(f"[daily_git_sync] pushed → {args.remote}/{args.branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
