#!/usr/bin/env python3
"""每日治理产物同步到 origin/master（交易脚本产物 + PM/QA/Ops 落盘）。

设计原则（对齐 docs/DEPLOYMENT.md / REVIEW_LOOP.md）：
- 只提交白名单路径：台账、cursor_queue、REQ/BUG、PLAN、测试报告、ops、波段日报、LLM 各类日报
- 禁止提交：交易核心代码、config.local、*.db、.venv、密钥
- 无变更则静默退出 0（默认不推企微「跳过」，防 18:45+20:30 双空刷屏；--notify-skip 可开）
- 有变更则 commit + push；成功/失败推企微摘要
- 跨平台排他锁：output/.daily_git_sync.lock（mkdir 原子创建），防双班重叠
- 不做 force push；不改 git config
- 建议 schtasks：18:45（台账主班）+ 20:30（承接 20:00 LLM 日报）

用法（产机）：
  .venv\\Scripts\\python.exe -u scripts\\daily_git_sync.py
  .venv\\Scripts\\python.exe -u scripts\\daily_git_sync.py --dry-run
  .venv\\Scripts\\python.exe -u scripts\\daily_git_sync.py --no-notify
  .venv\\Scripts\\python.exe -u scripts\\daily_git_sync.py --notify-skip
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_DIR = ROOT / "output" / ".daily_git_sync.lock"
LOCK_WAIT_SEC = 120
LOCK_POLL_SEC = 2

# 允许入库的相对路径前缀 / 精确文件
ALLOW_PREFIXES = (
    "pm/trade_journal/",
    "pm/cursor_queue/",
    "pm/requirements/",
    "pm/bugs/",
    "pm/archive/",
    "pm/dev/",
    "pm/test_reports/",
    "pm/ops/",
    "pm/agents/",
    "output/swing_daily/",
    "output/swing_pool/",
    "output/reviews/",
    "output/finance_manager/",
    "output/strategy_scorecard/",  # 每日策略记分卡（策略好坏的时间序列，必须进 git）
    "pm/strategy_review/",         # 周度复盘 + 参数采纳记录
    "daily_reports/",
    "docs/reviews/",  # 理财师脚本历史路径；新日报优先 daily_reports/
)

ALLOW_EXACT = {
    "docs/ROADMAP.md",
    "docs/CRON_JOBS.md",
    "docs/REVIEW_LOOP.md",
    "CRON_JOBS.md",
    "pm/BACKLOG.md",
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
    # Windows 产机默认 GBK；git/python 常吐 UTF-8 → 统一 utf-8 + replace，避免 Thread _readerthread 崩
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
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


def _release_lock() -> None:
    try:
        if LOCK_DIR.is_dir():
            for child in LOCK_DIR.iterdir():
                try:
                    child.unlink()
                except OSError:
                    pass
            LOCK_DIR.rmdir()
    except OSError:
        pass


def _acquire_lock(*, wait_sec: int = LOCK_WAIT_SEC) -> bool:
    """跨平台排他锁：用 mkdir 原子创建目录。成功返回 True。"""
    (ROOT / "output").mkdir(parents=True, exist_ok=True)
    deadline = time.time() + wait_sec
    while True:
        try:
            os.mkdir(LOCK_DIR)
            (LOCK_DIR / "pid").write_text(str(os.getpid()), encoding="utf-8")
            atexit.register(_release_lock)
            return True
        except FileExistsError:
            if time.time() >= deadline:
                return False
            time.sleep(LOCK_POLL_SEC)


def _load_webhook() -> str:
    """与 daily_close_report 同优先级：local → config → 环境变量。"""
    try:
        import yaml

        for rel, keys in (
            ("config.local.yaml", (("notify", "wecom_webhook"), ("notifier", "wecom_webhook"))),
            ("config.yaml", (("notify", "wecom_webhook"), ("notifier", "wecom_webhook"))),
        ):
            path = ROOT / rel
            if not path.exists():
                continue
            cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for a, b in keys:
                url = ((cfg.get(a) or {}).get(b) or "").strip()
                if url and "***" not in url and "YOUR_KEY" not in url:
                    return url
    except Exception:
        pass
    return (
        os.environ.get("WECOM_WEBHOOK")
        or os.environ.get("WECOM_WEBHOOK_URL")
        or ""
    ).strip()


def _notify_wecom(text: str, *, enabled: bool) -> None:
    """推送短摘要；失败只打日志，不改变 git 退出码。"""
    if not enabled:
        return
    if os.environ.get("NOTIFIER_DRY_RUN", "").strip() == "1":
        print(f"[daily_git_sync][dry-run wecom]\n{text}")
        return
    url = _load_webhook()
    if not url:
        print("[daily_git_sync] 无 webhook，跳过企微（git 结果不受影响）")
        return
    try:
        body = json.dumps(
            {"msgtype": "markdown", "markdown": {"content": text}},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
        if '"errcode":0' in resp:
            print("[daily_git_sync] 企微已推送")
        else:
            print(f"[daily_git_sync] 企微返回异常: {resp}", file=sys.stderr)
    except Exception as e:
        print(f"[daily_git_sync] 企微推送失败（git 结果不受影响）: {e}", file=sys.stderr)


def _remote_url(remote: str) -> str:
    r = _run(["git", "remote", "get-url", remote], check=False)
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def _head_sha() -> str:
    r = _run(["git", "rev-parse", "--short", "HEAD"], check=False)
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def _path_stats(paths: list[str]) -> dict[str, int]:
    """按业务类别计数，给 webhook 统计用。"""
    buckets = {
        "交易台账": 0,
        "日总结": 0,
        "波段日报/池": 0,
        "PM/队列/BUG": 0,
        "其它白名单": 0,
    }
    for raw in paths:
        p = raw.replace("\\", "/")
        if p.startswith("pm/trade_journal/"):
            buckets["交易台账"] += 1
        elif (
            p.startswith("output/daily_close_")
            or p.startswith("daily_reports/")
            or p.startswith("docs/reviews/")
            or p.startswith("output/reviews/")
            or p.startswith("output/finance_manager/")
            or p.startswith("output/pm_daily_report_")
        ):
            buckets["日总结"] += 1
        elif p.startswith("output/swing_daily/") or p.startswith("output/swing_pool/"):
            buckets["波段日报/池"] += 1
        elif p.startswith("pm/"):
            buckets["PM/队列/BUG"] += 1
        else:
            buckets["其它白名单"] += 1
    return buckets


def _summary_md(
    day: str,
    status: str,
    paths: list[str],
    *,
    detail: str = "",
    remote: str = "origin",
    branch: str = "master",
    remote_url: str = "",
    commit: str = "",
) -> str:
    """企微正文：是否上报成功 + 报到哪里 + 文件统计。"""
    ok = status in ("上报成功", "已 push")
    title = "✅ 上报成功" if ok else ("⏭️ 无变更跳过" if status in ("跳过",) else f"❌ {status}")
    dest = f"{remote}/{branch}"
    lines = [
        f"**DailyGitSync {day} — {title}**",
        f"结果: **{status}**",
        f"上报到: `{dest}`",
    ]
    if remote_url:
        lines.append(f"仓库: `{remote_url}`")
    if commit:
        lines.append(f"提交: `{commit}`")
    if detail:
        lines.append(detail)

    stats = _path_stats(paths)
    lines.append(f"统计: 共 **{len(paths)}** 个文件")
    for name, n in stats.items():
        if n:
            lines.append(f"- {name}: {n}")

    if paths:
        lines.append("清单:")
        for p in paths[:12]:
            lines.append(f"- `{p}`")
        if len(paths) > 12:
            lines.append(f"- …另有 {len(paths) - 12} 个")

    if ok:
        lines.append(f"主人可用 `git pull` 后在 `{dest}` 查看台账/日总结。")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync daily PM/trade artifacts to origin/master")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要提交的文件")
    parser.add_argument("--no-push", action="store_true", help="只 commit 不 push")
    parser.add_argument("--no-notify", action="store_true", help="不推企微")
    parser.add_argument(
        "--notify-skip",
        action="store_true",
        help="无白名单变更时也推企微「跳过」（默认不推，防双班刷屏）",
    )
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="master")
    args = parser.parse_args()
    do_notify = not args.no_notify and not args.dry_run
    day = datetime.now().strftime("%Y-%m-%d")
    remote_url = _remote_url(args.remote)

    def notify(status: str, paths: list[str], detail: str = "", commit: str = "") -> None:
        if status == "跳过" and not args.notify_skip:
            return
        _notify_wecom(
            _summary_md(
                day,
                status,
                paths,
                detail=detail,
                remote=args.remote,
                branch=args.branch,
                remote_url=remote_url,
                commit=commit,
            ),
            enabled=do_notify,
        )

    if not args.dry_run:
        if not _acquire_lock():
            msg = (
                f"[daily_git_sync] 获取锁失败（{LOCK_DIR} 仍被占用超过 {LOCK_WAIT_SEC}s），"
                "可能另一班 DailyGitSync 仍在跑"
            )
            print(msg, file=sys.stderr)
            notify("上报失败", [], detail="锁超时，未提交")
            return 3

    # safety: must be on target branch
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if branch != args.branch:
        msg = f"[daily_git_sync] 当前分支={branch}，期望={args.branch}，退出不提交"
        print(msg, file=sys.stderr)
        notify("上报失败", [], detail=f"分支不对: `{branch}` ≠ `{args.branch}`")
        return 2

    paths = _changed_paths()
    if not paths:
        print("[daily_git_sync] 无白名单变更，跳过")
        notify(
            "跳过",
            [],
            detail=f"无白名单变更（任务已跑）。目标仍是 `{args.remote}/{args.branch}`",
        )
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
        notify("跳过", paths, detail="add 后无 staged（可能被 .gitignore）")
        return 0

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
    commit = _head_sha()

    if args.no_push:
        print("[daily_git_sync] --no-push，结束")
        notify(
            "已 commit 未 push",
            paths,
            detail="`--no-push`，未上报远程",
            commit=commit,
        )
        return 0

    # pull --rebase --autostash：产机常有非白名单脏文件（scripts/ 等），
    # 无 autostash 时 rebase 直接失败 → commit 成功却不 push（BUG-dailygitsync-rebase）
    pull = _run(
        ["git", "pull", "--rebase", "--autostash", args.remote, args.branch],
        check=False,
    )
    if pull.returncode != 0:
        print(pull.stdout)
        print(pull.stderr, file=sys.stderr)
        print(
            "[daily_git_sync] pull --rebase --autostash 失败，仍尝试 push（本地白名单提交可能已领先）",
            file=sys.stderr,
        )
        push = _run(["git", "push", args.remote, f"HEAD:{args.branch}"], check=False)
        print(push.stdout)
        if push.returncode != 0:
            print(push.stderr, file=sys.stderr)
            print("[daily_git_sync] PUSH FAILED", file=sys.stderr)
            notify(
                "上报失败",
                paths,
                detail="`git pull --rebase --autostash` 失败且 `git push` 失败",
                commit=commit,
            )
            return push.returncode or pull.returncode
        commit = _head_sha() or commit
        print(f"[daily_git_sync] pushed（pull 失败后兜底）→ {args.remote}/{args.branch}")
        notify(
            "上报成功",
            paths,
            detail=(
                f"pull rebase 失败后兜底 push 成功 → `{args.remote}/{args.branch}`"
            ),
            commit=commit,
        )
        return 0

    push = _run(["git", "push", args.remote, f"HEAD:{args.branch}"], check=False)
    print(push.stdout)
    if push.returncode != 0:
        print(push.stderr, file=sys.stderr)
        print("[daily_git_sync] PUSH FAILED", file=sys.stderr)
        notify("上报失败", paths, detail="`git push` 失败", commit=commit)
        return push.returncode

    commit = _head_sha() or commit
    print(f"[daily_git_sync] pushed → {args.remote}/{args.branch} ({remote_url or 'url?'})")
    notify(
        "上报成功",
        paths,
        detail=f"白名单台账/日总结/PM 已 push 到 `{args.remote}/{args.branch}`",
        commit=commit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
