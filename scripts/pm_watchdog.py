#!/usr/bin/env python3
"""
scripts/pm_watchdog.py — PM Web 服务看门狗（增强版）

每5分钟由 Windows 计划任务调用，检查 http://localhost:8080 是否存活。
如果挂了，自动重启 Flask 应用。

增强点（相比初版）：
  - 使用文件锁防止并发运行
  - 修复 PYTHONIOENCODING 拼写错误
  - 重启前等待端口释放（避免 Address already in use）
  - 重启后多次健康检查（而非仅一次）
  - 详细日志（含 PID、端口、响应码）
  - 企微告警（重启失败时）

用法：
  python scripts/pm_watchdog.py

返回码：
  0 = 服务正常
  1 = 服务已重启且恢复
  2 = 服务重启后仍未恢复（已推送告警）
"""
import os
import sys
import time
import socket
import subprocess
import urllib.request
import urllib.error
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
APP_SCRIPT = str(WEB_DIR / "app.py")
PYTHON_EXE = os.environ.get("PM_WATCHDOG_PYTHON", "python")
LOG_FILE = ROOT / "output" / "pm_watchdog.log"
LOCK_FILE = ROOT / "output" / "pm_watchdog.lock"
MAX_RESTART_WAIT = 10  # 重启后最多等待秒数
HEALTH_CHECK_RETRIES = 3
HEALTH_CHECK_INTERVAL = 3  # 每次重试间隔秒数


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [WATCHDOG] {msg}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def acquire_lock() -> bool:
    """获取文件锁，防止并发运行"""
    try:
        if LOCK_FILE.exists():
            # 检查锁文件是否过期（超过10分钟认为僵死）
            age = time.time() - LOCK_FILE.stat().st_mtime
            if age > 600:
                log(f"锁文件已过期（{age:.0f}s），强制清除")
                LOCK_FILE.unlink()
            else:
                return False
        LOCK_FILE.write_text(str(os.getpid()))
        return True
    except Exception:
        return False


def release_lock():
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except Exception:
        pass


def get_port_pid(port: int) -> int | None:
    """获取占用指定端口的进程 PID"""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.split("\n"):
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "LISTENING" and i + 1 < len(parts):
                        return int(parts[i + 1])
    except Exception:
        pass
    return None


def is_port_free(port: int) -> bool:
    """检查端口是否空闲"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", port))
        s.close()
        return True
    except Exception:
        return False


def check_service(port: int = 8080, timeout: int = 5) -> tuple[bool, str]:
    """检查 PM 服务是否存活，返回 (alive, detail)"""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/", method="HEAD")
        resp = urllib.request.urlopen(req, timeout=timeout)
        pid = get_port_pid(port)
        return True, f"status={resp.status}, pid={pid}"
    except urllib.error.HTTPError as e:
        # 有响应但状态码异常，也算服务在运行
        pid = get_port_pid(port)
        return True, f"status={e.code}, pid={pid}"
    except Exception as e:
        return False, str(e)


def kill_port(port: int):
    """杀掉占用指定端口的进程"""
    pid = get_port_pid(port)
    if pid is None:
        return
    try:
        # 先尝试优雅终止
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T"],
            capture_output=True, timeout=10
        )
        log(f"已终止进程 PID={pid}（占用端口 {port}）")
    except Exception as e:
        log(f"终止进程 PID={pid} 失败: {e}")
    # 等待端口释放
    for _ in range(10):
        if is_port_free(port):
            return
        time.sleep(1)
    log(f"警告：端口 {port} 在终止进程后仍未释放")


def push_wecom_alert(message: str):
    """推送告警到企微 Webhook"""
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        webhook = (cfg.get("notify") or {}).get("wecom_webhook", "")
        if webhook:
            body = json.dumps({"msgtype": "text", "text": {"content": message}}).encode("utf-8")
            req = urllib.request.Request(
                webhook, data=body,
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=10)
            log("已推送告警到企微")
    except Exception as e:
        log(f"推送企微告警失败: {e}")


def restart_service() -> bool:
    """重启 PM 服务，返回是否成功"""
    # 1. 杀掉旧进程
    kill_port(8080)

    # 2. 启动新进程
    try:
        log(f"启动 PM 服务: {PYTHON_EXE} {APP_SCRIPT}")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"  # 修复：正确拼写

        stdout_log = open(ROOT / "output" / "pm_web.log", "a", encoding="utf-8")

        proc = subprocess.Popen(
            [PYTHON_EXE, APP_SCRIPT],
            cwd=str(ROOT),
            stdout=stdout_log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        log(f"PM 服务已启动 (PID={proc.pid})")

    except Exception as e:
        log(f"启动 PM 服务失败: {e}")
        return False

    # 3. 多次健康检查
    for i in range(HEALTH_CHECK_RETRIES):
        time.sleep(HEALTH_CHECK_INTERVAL)
        alive, detail = check_service()
        if alive:
            log(f"健康检查通过（第{i+1}次）: {detail}")
            return True
        else:
            log(f"健康检查失败（第{i+1}次）: {detail}")

    log("重启后健康检查全部失败")
    return False


def main():
    if not acquire_lock():
        log("已有实例运行中，退出")
        return 0

    try:
        log("--- 看门狗检查开始 ---")

        alive, detail = check_service()
        if alive:
            log(f"PM 服务运行正常 ({detail})")
            return 0

        log(f"PM 服务无响应 ({detail})，尝试重启...")
        if restart_service():
            log("PM 服务重启成功")
            return 1
        else:
            log("PM 服务重启失败，推送告警")
            push_wecom_alert(
                f"🚨 PM Web 服务重启失败\n"
                f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"请手动检查服务器！"
            )
            return 2
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
