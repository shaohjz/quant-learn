"""
scripts/auto_suggest.py — Agent 自动提出改进建议并写入 pm.db

功能：
  1. 扫描代码中的 TODO/FIXME/HACK/XXX 注释，自动创建 story
  2. 扫描 logs/ 目录下的错误日志，自动创建 bug
  3. 扫描测试失败输出，自动创建 bug
  4. 去重：同一文件同一行的建议只创建一次（记录到 data/auto_suggest_cache.json）

用法：
  python scripts/auto_suggest.py              # 全量扫描，输出建议但不重复创建
  python scripts/auto_suggest.py --dry-run    # 只打印，不写 pm.db
  python scripts/auto_suggest.py --force      # 强制重新创建（忽略缓存）

定时调用（建议通过 OpenClaw cron 或 Windows 计划任务）：
  每天 09:00 跑一次，自动提需求
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "auto_suggest_cache.json"
PM_CLI = ROOT / "scripts" / "pm_cli.py"
DRY = False
FORCE = False

# 扫描目录（相对于 ROOT）
SCAN_DIRS = ["scripts", "sim", "strategies", "runners", "web", "broker", "decision", "ml", "pm"]
# 跳过的目录
SKIP_DIRS = ["__pycache__", ".venv", "venv", "node_modules", ".git"]
# 注释模式
COMMENT_PATTERNS = [
    (re.compile(r"#\s*(TODO|FIXME|HACK|XXX|BUG)[\s:(]+(.*)", re.IGNORECASE), "code_todo"),
    (re.compile(r"//\s*(TODO|FIXME|HACK|XXX|BUG)[\s:(]+(.*)", re.IGNORECASE), "code_todo"),
]
# 日志错误关键词
LOG_ERROR_KEYWORDS = ["error", "exception", "traceback", "failed", "failure", "fatal"]


def load_cache() -> dict:
    if CACHE_PATH.exists():
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"todos": {}, "logs": {}, "version": 1}


def save_cache(cache: dict):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def make_todo_key(filepath: str, line_num: int, keyword: str) -> str:
    return f"{filepath}:{line_num}:{keyword.lower()}"


def scan_todos(cache: dict) -> list[tuple[str, str]]:
    """扫描代码中的 TODO/FIXME 等，返回 [(title, desc)]"""
    results = []
    todo_cache = cache.get("todos", {})
    now_iso = datetime.now().strftime("%Y-%m-%d")

    for scan_dir in SCAN_DIRS:
        dir_path = ROOT / scan_dir
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            # 跳过临时/归档文件
            if any(part.startswith("_") and part not in ("__init__.py",) for part in py_file.parts if part.startswith("_")):
                if py_file.stem.startswith("_") and py_file.stem not in ("__init__",):
                    continue
            rel_path = str(py_file.relative_to(ROOT)).replace("\\", "/")
            try:
                with open(py_file, "r", encoding="utf-8", errors="replace") as f:
                    for line_num, line in enumerate(f, 1):
                        for pattern, _ in COMMENT_PATTERNS:
                            m = pattern.search(line)
                            if m:
                                keyword = m.group(1).upper()
                                content = m.group(2).strip()
                                key = make_todo_key(rel_path, line_num, keyword)
                                if not FORCE and key in todo_cache:
                                    continue
                                title = f"[{keyword}] {content[:50]}" if content else f"[{keyword}] {rel_path}:{line_num}"
                                desc = (
                                    f"自动扫描发现代码注释：\n"
                                    f"- 文件：{rel_path}\n"
                                    f"- 行号：{line_num}\n"
                                    f"- 类型：{keyword}\n"
                                    f"- 内容：{content}\n"
                                    f"- 发现日期：{now_iso}\n"
                                    f"\n建议：请评估是否需要创建正式需求或立即修复。"
                                )
                                results.append((title, desc, key, "story" if keyword in ("TODO",) else "bug"))
                                todo_cache[key] = now_iso
            except Exception as e:
                print(f"  [warn] 无法读取 {rel_path}: {e}", file=sys.stderr)

    cache["todos"] = todo_cache
    return results


def scan_logs(cache: dict) -> list[tuple[str, str]]:
    """扫描 logs/ 目录下的错误，返回 [(title, desc)]"""
    results = []
    log_cache = cache.get("logs", {})
    logs_dir = ROOT / "logs"
    if not logs_dir.exists():
        return results

    now_iso = datetime.now().strftime("%Y-%m-%d")

    for log_file in logs_dir.rglob("*.log"):
        rel_path = str(log_file.relative_to(ROOT)).replace("\\", "/")
        mtime = datetime.fromtimestamp(log_file.stat().st_mtime).strftime("%Y-%m-%d")
        key = f"{rel_path}:{mtime}"
        if not FORCE and key in log_cache:
            continue

        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            error_lines = []
            for i, line in enumerate(lines[-500:], max(0, len(lines) - 500)):  # 只看最后 500 行
                if any(kw in line.lower() for kw in LOG_ERROR_KEYWORDS):
                    error_lines.append((i + 1, line.rstrip()))

            if error_lines:
                title = f"[LOG_ERROR] {log_file.stem} 发现 {len(error_lines)} 处错误日志"
                desc_lines = [
                    f"自动扫描发现日志错误：",
                    f"- 日志文件：{rel_path}",
                    f"- 发现日期：{now_iso}",
                    f"- 错误行数：{len(error_lines)}",
                    "",
                    "最近错误片段：",
                ]
                for ln, content in error_lines[:5]:
                    desc_lines.append(f"  行{ln}: {content[:120]}")
                desc_lines.append("\n建议：请排查日志中的错误是否需要修复。")
                results.append((title, "\n".join(desc_lines), key, "bug"))
                log_cache[key] = now_iso
        except Exception as e:
            print(f"  [warn] 无法读取日志 {rel_path}: {e}", file=sys.stderr)

    cache["logs"] = log_cache
    return results


def create_task(title: str, desc: str, task_type: str = "story", priority: str = "P2") -> bool:
    """调用 pm_cli.py 创建任务，返回是否成功"""
    if DRY:
        print(f"  [dry-run] 将创建 {task_type}: {title}")
        return True

    cmd = [
        sys.executable,
        str(PM_CLI),
        "create",
        task_type,
        title,
        "--desc", desc,
        "--priority", priority,
        "--status", "pending",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(ROOT),
        )
        output = result.stdout.strip() or result.stderr.strip()
        if result.returncode == 0:
            print(f"  [ok] 已创建 {task_type}: {title}")
            print(f"       {output}")
            return True
        else:
            print(f"  [fail] 创建失败: {output}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"  [error] 调用 pm_cli.py 失败: {e}", file=sys.stderr)
        return False


def run(dry_run: bool = False, force: bool = False):
    global DRY, FORCE
    DRY = dry_run
    FORCE = force

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] auto_suggest 开始扫描...")
    cache = load_cache()
    created = 0

    # 1. 扫描 TODO/FIXME
    print("\n--- 扫描代码注释 (TODO/FIXME/HACK/XXX) ---")
    todos = scan_todos(cache)
    print(f"发现 {len(todos)} 条新建议")
    for title, desc, key, task_type in todos:
        priority = "P1" if task_type == "bug" else "P2"
        if create_task(title, desc, task_type, priority):
            created += 1

    # 2. 扫描日志
    print("\n--- 扫描日志错误 ---")
    log_issues = scan_logs(cache)
    print(f"发现 {len(log_issues)} 条日志异常")
    for title, desc, key, task_type in log_issues:
        if create_task(title, desc, task_type, "P1"):
            created += 1

    # 保存缓存
    save_cache(cache)

    print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 完成，共创建 {created} 条任务")
    return created


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent 自动提出改进建议并写入 pm.db")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写 pm.db")
    parser.add_argument("--force", action="store_true", help="强制重新创建（忽略缓存）")
    args = parser.parse_args()
    run(dry_run=args.dry_run, force=args.force)
