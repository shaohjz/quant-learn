#!/usr/bin/env python3
"""产机时钟：一条 cron 替代扫描类 Windows 任务计划。

工作台角色 3-windows 用 OpenClaw systemEvent 每 10 分钟调用本脚本。
一次一天的任务用 stamp 去重；Pulse 自己判断交易时段。

用法：
  python scripts/prod_clock.py
  python scripts/prod_clock.py --dry-run
  python scripts/prod_clock.py --status
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.trade_calendar import is_trading_day  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")
STAMP_ROOT = ROOT / "output" / "prod_clock"
LOG = ROOT / "output" / "prod_clock.log"

PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = ROOT / ".venv" / "bin" / "python"


def now_sh() -> datetime:
    return datetime.now(TZ)


def log(msg: str) -> None:
    STAMP_ROOT.parent.mkdir(parents=True, exist_ok=True)
    line = f"{now_sh().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def hm(dt: datetime) -> int:
    return dt.hour * 100 + dt.minute


def trading_day(dt: datetime) -> bool:
    """交易日判定：schtasks 已限周一~五触发，这里挡节假日。

    is_trading_day 内部用 akshare 官方日历（缓存 data/trade_dates.json，
    7 天 TTL）；拉不到且无缓存时回退周末判定（不抛错）。
    """
    try:
        return is_trading_day(dt.date())
    except Exception:
        return dt.weekday() < 5


def stamp_path(day: str, job_id: str) -> Path:
    return STAMP_ROOT / day / f"{job_id}.done"


def already_done(day: str, job_id: str) -> bool:
    return stamp_path(day, job_id).exists()


def mark_done(day: str, job_id: str) -> None:
    p = stamp_path(day, job_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(now_sh().isoformat(), encoding="utf-8")


def python_cmd(rel: str, extra: list[str] | None = None) -> list[str]:
    return [str(PY), "-u", str(ROOT / rel), *(extra or [])]


def run_cmd(job_id: str, cmd: list[str], extra_env: dict[str, str] | None = None) -> int:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if extra_env:
        env.update(extra_env)
    log(f"RUN {job_id}: {' '.join(cmd)}")
    p = subprocess.run(cmd, cwd=str(ROOT), env=env)
    log(f"RC  {job_id}: {p.returncode}")
    return int(p.returncode)


def git_sync_env() -> dict[str, str]:
    home = "C:/Users/Administrator"
    return {
        "HOME": r"C:\Users\Administrator",
        "GIT_SSH_COMMAND": (
            "ssh -o StrictHostKeyChecking=accept-new "
            f"-o UserKnownHostsFile={home}/.ssh/known_hosts "
            f"-i {home}/.ssh/id_ed25519"
        ),
    }


# 窗口对齐 OpenClaw */10；一次一天任务在窗口内只跑一次。
ONCE_JOBS: list[dict] = [
    {
        "id": "morning_scan",
        "start": 830,
        "end": 839,
        "steps": [python_cmd("scripts/scanner_with_fallback.py")],
    },
    {
        "id": "swing_pool",
        "start": 840,
        "end": 859,
        "steps": [
            python_cmd(
                "scripts/swing_pool_builder.py",
                ["--max-pool", "50", "--min-score", "70", "--mode", "auto", "--force"],
            ),
            python_cmd("scripts/swing_auto.py", ["--title", "盘前波段扫描报告"]),
        ],
    },
    {
        "id": "swing_daily",
        "start": 1600,
        "end": 1609,
        "steps": [python_cmd("scripts/swing_daily_report.py")],
    },
    {
        "id": "bank_swing",
        "start": 1600,
        "end": 1619,
        "steps": [python_cmd("scripts/bank_swing_daily.py")],
    },
    {
        "id": "journal",
        "start": 1610,
        "end": 1619,
        "steps": [python_cmd("scripts/trade_journal.py")],
    },
    {
        "id": "close",
        "start": 1620,
        "end": 1629,
        "steps": [python_cmd("scripts/daily_close_report.py")],
    },
    {
        "id": "strategy_review",
        "start": 1630,
        "end": 1649,
        "steps": [python_cmd("scripts/strategy_review.py", ["--write-spec", "--quiet"])],
    },
    {
        "id": "git_sync",
        "start": 1840,
        "end": 1914,
        "steps": [python_cmd("scripts/daily_git_sync.py")],
        "env": "git",
    },
    {
        "id": "git_sync_evening",
        "start": 2030,
        "end": 2059,
        "steps": [python_cmd("scripts/daily_git_sync.py")],
        "env": "git",
    },
]

# 这些脚本支持 --no-push。收盘简报 daily_close_report 故意不在名单里，仍推企微。
_NO_PUSH_SCRIPTS = (
    "scripts/quant_pulse.py",
    "scripts/swing_auto.py",
    "scripts/swing_daily_report.py",
    "scripts/bank_swing_daily.py",
    "scripts/trade_journal.py",
    "scripts/strategy_review.py",
    "scripts/portfolio_alert.py",
    "scripts/swing_intraday_watch.py",
)


def mute_intraday_wecom() -> bool:
    try:
        from sim.config import notify_intraday_push_enabled

        return not notify_intraday_push_enabled()
    except Exception:
        return True


def _script_rel(step: list[str]) -> str:
    for part in step:
        p = str(part).replace("\\", "/")
        if "/scripts/" in p:
            return "scripts/" + p.rsplit("/scripts/", 1)[-1]
        if p.startswith("scripts/"):
            return p
    return ""


def apply_wecom_policy(step: list[str]) -> list[str]:
    """盘中企微关闭时，给支持 --no-push 的脚本补上该参数。"""
    if not mute_intraday_wecom():
        return step
    rel = _script_rel(step)
    if rel in _NO_PUSH_SCRIPTS and "--no-push" not in step:
        return list(step) + ["--no-push"]
    return step


def in_pulse_clock(hmi: int) -> bool:
    return (930 <= hmi <= 1130) or (1300 <= hmi <= 1450)


def plan(dt: datetime) -> list[dict]:
    if not trading_day(dt):
        return []
    hmi = hm(dt)
    day = dt.strftime("%Y-%m-%d")
    jobs: list[dict] = []
    if in_pulse_clock(hmi):
        jobs.append(
            {
                "id": "pulse",
                "once": False,
                "steps": [apply_wecom_policy(python_cmd("scripts/quant_pulse.py"))],
            }
        )
    for spec in ONCE_JOBS:
        if spec["start"] <= hmi <= spec["end"] and not already_done(day, spec["id"]):
            jobs.append(
                {
                    **spec,
                    "once": True,
                    "steps": [apply_wecom_policy(s) for s in spec["steps"]],
                }
            )
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    dt = now_sh()
    day = dt.strftime("%Y-%m-%d")
    jobs = plan(dt)

    if args.status:
        done = sorted(p.stem for p in (STAMP_ROOT / day).glob("*.done")) if (STAMP_ROOT / day).exists() else []
        print(
            json.dumps(
                {
                    "now": dt.isoformat(),
                    "weekday": dt.weekday(),
                    "trading_day": trading_day(dt),
                    "hm": hm(dt),
                    "due": [j["id"] for j in jobs],
                    "done_today": done,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not trading_day(dt):
        log("非交易日（周末或节假日），时钟空转")
        return 0
    if not jobs:
        log(f"无到期任务 hm={hm(dt)}")
        return 0

    worst = 0
    for job in jobs:
        if args.dry_run:
            log(f"DRY {job['id']}")
            continue
        extra_env = git_sync_env() if job.get("env") == "git" else None
        rc = 0
        for step in job["steps"]:
            rc = run_cmd(job["id"], step, extra_env) or rc
        if job.get("once") and rc == 0:
            mark_done(day, job["id"])
        worst = worst or rc
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
