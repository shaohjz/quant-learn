"""
scripts/devops_watch.py — DevOps Agent 主脚本
职责：
  1. 检测 vqlearn 进程是否存活，挂了自动拉起
  2. 检测代码是否有新 commit 未生效（进程启动时间 < 最新 commit 时间），有则重启
  3. 检测 sim_executor 是否加载成功（读 vqlearn 日志最后 N 行）
  4. ⚠️ 不再自己发企微通知！统一由 DevOps Agent (cron) 读输出后推送。

用法：
  python scripts/devops_watch.py            # 完整检查 + 自动修复
  python scripts/devops_watch.py --dry-run   # 只打印，不操作
  # Windows 计划任务每 30 分钟调一次（由 DevOps-Agent cron 管理）
"""
from __future__ import annotations

import sys
import os
import json
import logging
import subprocess
import psutil  # type: ignore
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("devops-watch")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# 不再自己发通知，统一由 DevOps Agent 推送
# 保留 WEBHOOK_URL 供未来扩展用
WEBHOOK_URL: str | None = None
try:
    cfg = (ROOT / "config.local.yaml").read_text(encoding="utf-8")
    import yaml
    d = yaml.safe_load(cfg) or {}
    WEBHOOK_URL = (d.get("notifier") or {}).get("wecom_webhook")
except Exception:
    pass


def _log(msg: str) -> None:
    """打印到日志，不自己发企微（由 Agent 统一推送）"""
    LOG.info(f"[notify] {msg}")


def _get_vqlearn_proc() -> list[dict]:
    """返回正在跑的 vqlearn runner 进程列表"""
    results = []
    for p in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            cmd = p.info["cmdline"] or []
            if not cmd:
                continue
            cmd_str = " ".join(cmd)
            if "python" in cmd[0].lower() and "vqlearn.runners.run_paper_with_strategy" in cmd_str:
                results.append({
                    "pid": p.info["pid"],
                    "create_time": p.info["create_time"],
                    "cmd": cmd_str[:200],
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return results


def _get_latest_commit_time() -> float:
    """返回最新 commit 的 unix 时间戳"""
    out = subprocess.check_output(
        ["git", "log", "-1", "--format=%ct"],
        cwd=str(ROOT),
        stderr=subprocess.DEVNULL,
    ).decode().strip()
    return float(out) if out else 0.0


def _restart_vqlearn(dry_run: bool = False) -> bool:
    """杀所有旧进程，拉起新的。返回是否成功。"""
    procs = _get_vqlearn_proc()
    if not procs:
        LOG.info("[restart] no vqlearn process found, will start new one")
    for p in procs:
        pid = p["pid"]
        LOG.info(f"[restart] killing old vqlearn PID={pid}")
        if not dry_run:
            try:
                os.kill(pid, 9)
            except Exception as e:
                LOG.warning(f"[restart] kill PID={pid} failed: {e}")

    # 等进程完全退出
    import time; time.sleep(2)

    # 只拉一个新进程
    bat = ROOT / "scripts" / "vqlearn_live_runner.bat"
    if not bat.exists():
        LOG.error(f"[restart] bat not found: {bat}")
        return False

    LOG.info(f"[restart] starting {bat}")
    if not dry_run:
        subprocess.Popen(
            f'cmd /c start /min "" "{bat}"',
            shell=True,
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        import time; time.sleep(5)
    return True


def _check_sim_executor_in_log() -> str | None:
    """读 vqlearn_live.log 最后 50 行，检查是否有 sim_executor 加载失败。
    返回错误描述，没有则返回 None。"""
    log_path = ROOT / "output" / "vqlearn_live.log"
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-50:]
        for line in reversed(tail):
            if "sim_executor 未加载" in line or "_sim_execute_trade is None" in line:
                return line.strip()
        # 反过来找 success 标记
        for line in tail:
            if "sim_executor loaded OK" in line or "_sim_execute_trade = <" in line:
                return None
    except Exception as e:
        LOG.warning(f"[log-check] {e}")
    return None


def run(dry_run: bool = False) -> None:
    LOG.info("=" * 60)
    LOG.info("[devops-watch] start")

    now_ts = datetime.now().timestamp()
    issues = []

    # ---- 1. 进程存活 ----
    procs = _get_vqlearn_proc()
    if not procs:
        msg = "⚠️ DevOps 告警：vqlearn 进程不存在！"
        LOG.warning(msg)
        issues.append(msg)
        if not dry_run:
            _restart_vqlearn(dry_run=False)
            _log(f"vqlearn 进程不存在，已自动重启")
    else:
        for p in procs:
            started = datetime.fromtimestamp(p["create_time"]).strftime("%m-%d %H:%M")
            LOG.info(f"[alive] vqlearn PID={p['pid']} started={started}")

    # ---- 2. 代码版本对比 ----
    if procs:
        latest_commit_ts = _get_latest_commit_time()
        for p in procs:
            proc_start_ts = p["create_time"]
            drift = latest_commit_ts - proc_start_ts
            if drift > 60:  # commit 比进程启动晚 > 60 秒，认为代码有更新
                msg = f"⚠️ DevOps 告警：代码已更新但 vqlearn 未重启（commit 比进程新 {drift:.0f}s）"
                LOG.warning(msg)
                issues.append(msg)
                if not dry_run:
                    _log(
                        f"检测到新代码提交，vqlearn 自动重启生效。"
                        f" 进程启动: {datetime.fromtimestamp(proc_start_ts).strftime('%m-%d %H:%M')}"
                        f" | 最新 commit: {datetime.fromtimestamp(latest_commit_ts).strftime('%m-%d %H:%M')}"
                    )
                    _restart_vqlearn(dry_run=False)
                    break  # 重启一次就够了

    # ---- 3. sim_executor 加载检查 ----
    err = _check_sim_executor_in_log()
    if err:
        msg = f"⚠️ DevOps 告警：sim_executor 加载异常：{err}"
        LOG.warning(msg)
        issues.append(msg)
        if not dry_run:
            _log(f"sim_executor 加载失败，买入信号无法执行！DevOps 将尝试重启 vqlearn 进程。")
            _restart_vqlearn(dry_run=False)

    # ---- 4. 进程重启后验证 ----
    if issues and not dry_run:
        import time; time.sleep(8)
        procs2 = _get_vqlearn_proc()
        if procs2:
            LOG.info(f"[verify] restart OK, new PID={procs2[0]['pid']}")
        else:
            LOG.error("[verify] restart failed, process still not running!")
            _log("vqlearn 重启后进程仍未拉起，请手动检查！")

    if not issues:
        LOG.info("[devops-watch] all checks passed")

    LOG.info("[devops-watch] done")
    LOG.info("=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只检查，不操作")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
