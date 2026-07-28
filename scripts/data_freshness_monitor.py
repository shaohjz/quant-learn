#!/usr/bin/env python3
"""
scripts/data_freshness_monitor.py — 数据新鲜度监控 (REQ-067)
=================================================================

检查各数据源的最新更新时间，超期自动告警。

监控项：
  1. sim_positions.updated_at — 最新持仓价格是否在 N 小时内
  2. sim_daily_nav.trade_date   — 最新 NAV 是否覆盖到当天
  3. strategy_shadow_signals.shadow_date — 最新信号日期
  4. watchlist_history.last_alert_at — 最近告警时间（可选）

告警输出：
  - 控制台日志（结构化的 freshness report）
  - PM alerts 表（data/ops_runtime.db 中的 freshness_alerts；与需求 markdown 分离）
  - 可选企微通知（集成 notify 模块）

配置：
  - 通过环境变量或代码常量配置告警阈值
  - FRESHNESS_HOURS: 默认 24 小时
  - alert_log 输出到 output/freshness_report.json

集成：
  - 可作为独立脚本运行: python scripts/data_freshness_monitor.py
  - 可被 ops_daily_check.py 调用为模块函数
  - 支持 --quiet 静默模式（仅异常时输出）
  - 支持 --json 输出 JSON 结果到 stdout
  - 支持 --notify 推送告警通知
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── 路径配置 ──────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SIM_DB_PATH = ROOT / "data" / "sim_live_mirror.db"
PM_DB_PATH = ROOT / "data" / "ops_runtime.db"  # 运行态告警；需求已迁 markdown
OPS_RUNTIME_DB = PM_DB_PATH
OUTPUT_DIR = ROOT / "output"
REPORT_PATH = OUTPUT_DIR / "freshness_report.json"

# ── 阈值配置 ──────────────────────────────────────────────────────────
# 可通过环境变量覆盖
DEFAULT_FRESHNESS_HOURS = int(os.environ.get("FRESHNESS_HOURS", "24"))
# 单个数据源可单独配置
DATA_SOURCE_THRESHOLDS: Dict[str, int] = {
    "sim_positions": int(os.environ.get("FRESHNESS_POSITIONS_HOURS", str(DEFAULT_FRESHNESS_HOURS))),
    "sim_daily_nav": int(os.environ.get("FRESHNESS_NAV_HOURS", str(DEFAULT_FRESHNESS_HOURS))),
    "strategy_shadow_signals": int(os.environ.get("FRESHNESS_SIGNALS_HOURS", str(DEFAULT_FRESHNESS_HOURS))),
    "watchlist_history": int(os.environ.get("FRESHNESS_WATCHLIST_HOURS", str(DEFAULT_FRESHNESS_HOURS))),
}


# ══════════════════════════════════════════════════════════════════════
# 数据源检查器
# ══════════════════════════════════════════════════════════════════════

def _parse_timestamp(ts: Optional[str]) -> Optional[datetime]:
    """尝试多种格式解析时间戳。"""
    if ts is None:
        return None
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(ts, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _hours_ago(dt: Optional[datetime], now: Optional[datetime] = None) -> Optional[float]:
    """计算 dt 距今多少小时。"""
    if dt is None:
        return None
    now = now or datetime.now()
    return (now - dt).total_seconds() / 3600


def check_sim_positions(
    db_path: Path,
    threshold_hours: int,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """检查 sim_positions.updated_at 新鲜度。

    Returns:
        dict with keys: source, ok, latest_ts, age_hours, threshold_hours, message
    """
    source = "sim_positions"
    now = now or datetime.now()
    result: Dict[str, Any] = {
        "source": source,
        "check_type": "timestamp",
        "threshold_hours": threshold_hours,
    }
    try:
        if not db_path.exists():
            result.update(ok=False, latest_ts=None, age_hours=None,
                          message=f"数据库不存在: {db_path}")
            return result
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT MAX(updated_at) FROM sim_positions")
        row = cur.fetchone()
        conn.close()
        latest_ts_str = row[0] if row else None
        latest_dt = _parse_timestamp(latest_ts_str)
        age_h = _hours_ago(latest_dt, now)
        result["latest_ts"] = latest_ts_str
        result["age_hours"] = round(age_h, 1) if age_h is not None else None
        if latest_dt is None:
            result["ok"] = True  # 无数据不算异常，但需要标记
            result["message"] = f"[{source}] 仓位表无数据"
        elif age_h is not None and age_h > threshold_hours:
            result["ok"] = False
            result["message"] = (
                f"[{source}] 仓位价格已过时: "
                f"最新 {latest_ts_str} ({age_h:.1f}h 前), 阈值 {threshold_hours}h"
            )
        else:
            result["ok"] = True
            result["message"] = (
                f"[{source}] 仓位价格新鲜: 最新 {latest_ts_str} ({age_h:.1f}h 前)"
            )
    except Exception as e:
        result.update(ok=False, latest_ts=None, age_hours=None,
                       message=f"[{source}] 检查异常: {e}")
    return result


def check_sim_daily_nav(
    db_path: Path,
    threshold_hours: int,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """检查 sim_daily_nav.trade_date 是否覆盖到当天。

    threshold_hours 用于计算"今天 vs 最新交易日期"的容忍度。
    对于日级数据，按自然日计算过期天数。
    """
    source = "sim_daily_nav"
    now = now or datetime.now()
    result: Dict[str, Any] = {
        "source": source,
        "check_type": "date",
        "threshold_hours": threshold_hours,
    }
    try:
        if not db_path.exists():
            result.update(ok=False, latest_ts=None, age_hours=None,
                          message=f"数据库不存在: {db_path}")
            return result
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT MAX(trade_date) FROM sim_daily_nav")
        row = cur.fetchone()
        conn.close()
        latest_date_str = row[0] if row else None
        latest_dt = _parse_timestamp(latest_date_str)
        result["latest_ts"] = latest_date_str
        if latest_dt is None:
            result["ok"] = True
            result["age_hours"] = None
            result["message"] = f"[{source}] NAV 表无数据"
        else:
            # 按日计算差距
            today = now.date()
            nav_date = latest_dt.date()
            days_behind = (today - nav_date).days
            age_hours = days_behind * 24
            result["age_hours"] = age_hours
            if days_behind <= 0:
                result["ok"] = True
                result["message"] = f"[{source}] NAV 已覆盖到今天 ({latest_date_str})"
            elif age_hours > threshold_hours:
                result["ok"] = False
                result["message"] = (
                    f"[{source}] NAV 数据过时: "
                    f"最新 {latest_date_str} ({days_behind}d 前), 阈值 {threshold_hours}h"
                )
            else:
                result["ok"] = True
                result["message"] = (
                    f"[{source}] NAV 新鲜: 最新 {latest_date_str} ({days_behind}d 前)"
                )
    except Exception as e:
        result.update(ok=False, latest_ts=None, age_hours=None,
                       message=f"[{source}] 检查异常: {e}")
    return result


def check_strategy_shadow_signals(
    db_path: Path,
    threshold_hours: int,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """检查 strategy_shadow_signals.shadow_date 是否覆盖到今天。"""
    source = "strategy_shadow_signals"
    now = now or datetime.now()
    result: Dict[str, Any] = {
        "source": source,
        "check_type": "date",
        "threshold_hours": threshold_hours,
    }
    try:
        if not db_path.exists():
            result.update(ok=False, latest_ts=None, age_hours=None,
                          message=f"数据库不存在: {db_path}")
            return result
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT MAX(shadow_date) FROM strategy_shadow_signals")
        row = cur.fetchone()
        # Also get count for today
        today_str = now.strftime("%Y-%m-%d")
        cur.execute(
            "SELECT COUNT(*) FROM strategy_shadow_signals WHERE shadow_date = ?",
            (today_str,),
        )
        today_count = cur.fetchone()[0]
        conn.close()
        latest_date_str = row[0] if row else None
        latest_dt = _parse_timestamp(latest_date_str)
        result["latest_ts"] = latest_date_str
        result["today_signal_count"] = today_count
        if latest_dt is None:
            result["ok"] = True
            result["age_hours"] = None
            result["message"] = f"[{source}] 信号表无数据"
        else:
            today = now.date()
            sig_date = latest_dt.date()
            days_behind = (today - sig_date).days
            age_hours = days_behind * 24
            result["age_hours"] = age_hours
            if days_behind <= 0:
                result["ok"] = True
                result["message"] = (
                    f"[{source}] 信号已覆盖到今天 ({latest_date_str}), "
                    f"今日信号 {today_count} 条"
                )
            elif age_hours > threshold_hours:
                result["ok"] = False
                result["message"] = (
                    f"[{source}] 信号数据过时: "
                    f"最新 {latest_date_str} ({days_behind}d 前), 阈值 {threshold_hours}h"
                )
            else:
                result["ok"] = True
                result["message"] = (
                    f"[{source}] 信号新鲜: 最新 {latest_date_str} ({days_behind}d 前)"
                )
    except Exception as e:
        result.update(ok=False, latest_ts=None, age_hours=None,
                       message=f"[{source}] 检查异常: {e}")
    return result


def check_watchlist_history(
    db_path: Path,
    threshold_hours: int,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """检查 watchlist_history.last_alert_at 新鲜度。

    此检查为信息性（不阻止），因为并非每天都有个警告警。
    """
    source = "watchlist_history"
    now = now or datetime.now()
    result: Dict[str, Any] = {
        "source": source,
        "check_type": "timestamp",
        "threshold_hours": threshold_hours,
    }
    try:
        if not db_path.exists():
            result.update(ok=True, latest_ts=None, age_hours=None,
                          message=f"数据库不存在: {db_path} (跳过)")
            return result
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        # 总条数
        cur.execute("SELECT COUNT(*) FROM watchlist_history")
        total_count = cur.fetchone()[0]
        # 最近告警
        cur.execute(
            "SELECT MAX(last_alert_at) FROM watchlist_history WHERE last_alert_at IS NOT NULL"
        )
        row = cur.fetchone()
        # 最近发现时间
        cur.execute("SELECT MAX(added_at) FROM watchlist_history")
        latest_added = cur.fetchone()[0]
        conn.close()
        latest_alert_str = row[0] if row else None
        latest_alert_dt = _parse_timestamp(latest_alert_str)
        age_h = _hours_ago(latest_alert_dt, now)
        result["latest_ts"] = latest_alert_str
        result["age_hours"] = round(age_h, 1) if age_h is not None else None
        result["total_items"] = total_count
        result["latest_added_at"] = latest_added
        result["ok"] = True  # watchlist_history 不阻报告警
        if latest_alert_dt is None:
            result["message"] = f"[{source}] 无告警记录 (总计 {total_count} 条)"
        elif age_h is not None and age_h > threshold_hours:
            result["message"] = (
                f"[{source}] 最近告警较旧: "
                f"{latest_alert_str} ({age_h:.1f}h 前), 总计 {total_count} 条"
            )
        else:
            result["message"] = (
                f"[{source}] 告警记录新鲜: {latest_alert_str} ({age_h:.1f}h 前)"
            )
    except Exception as e:
        result.update(ok=True, latest_ts=None, age_hours=None,
                       message=f"[{source}] 检查异常: {e}")
    return result


# ══════════════════════════════════════════════════════════════════════
# PM Alerts 输出
# ══════════════════════════════════════════════════════════════════════

def ensure_alerts_table(db_path: Path) -> None:
    """确保 ops_runtime.db 中有 freshness_alerts 表。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS freshness_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_time TEXT NOT NULL,
            source TEXT NOT NULL,
            ok INTEGER NOT NULL,
            age_hours REAL,
            latest_ts TEXT,
            threshold_hours INTEGER,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 清理旧记录（保留最近 7 天的）
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("DELETE FROM freshness_alerts WHERE created_at < ?", (cutoff,))
    conn.commit()
    conn.close()


def save_alerts_to_pm(
    db_path: Path,
    results: List[Dict[str, Any]],
    check_time: Optional[str] = None,
) -> int:
    """将新鲜度检查结果写入 PM alerts 表。

    Returns:
        写入条数
    """
    ensure_alerts_table(db_path)
    check_time = check_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    count = 0
    for r in results:
        cur.execute(
            """INSERT INTO freshness_alerts
               (check_time, source, ok, age_hours, latest_ts, threshold_hours, message)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                check_time,
                r.get("source", "unknown"),
                1 if r.get("ok") else 0,
                r.get("age_hours"),
                r.get("latest_ts"),
                r.get("threshold_hours"),
                r.get("message", ""),
            ),
        )
        count += 1
    conn.commit()
    conn.close()
    return count


# ══════════════════════════════════════════════════════════════════════
# 通知推送
# ══════════════════════════════════════════════════════════════════════

def notify_alerts(
    results: List[Dict[str, Any]],
    check_time: Optional[str] = None,
) -> bool:
    """通过企微通知异常告警。需要 config.yaml 中配置 notify.wecom_webhook。"""
    failed = [r for r in results if not r.get("ok")]
    if not failed:
        return True

    check_time = check_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"⚠️ 数据新鲜度告警 ({check_time})"]
    for r in failed:
        lines.append(f"  ❌ {r.get('source', '?')}: {r.get('message', '')}")
    content = "\n".join(lines)

    try:
        from scripts.notify import send_text
        result = send_text(content)
        return result.get("errcode", -1) == 0
    except ImportError:
        # 如果 notify 模块不可用，只打印
        print(f"[freshness] notify 模块不可用，内容:\n{content}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[freshness] 通知发送失败: {e}", file=sys.stderr)
        return False


# ══════════════════════════════════════════════════════════════════════
# 主执行逻辑
# ══════════════════════════════════════════════════════════════════════

def run_all_checks(
    db_path: Optional[Path] = None,
    thresholds: Optional[Dict[str, int]] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """运行全部数据新鲜度检查。

    Args:
        db_path: sim_live_mirror.db 路径，默认 SIM_DB_PATH
        thresholds: 各数据源阈值字典，默认 DATA_SOURCE_THRESHOLDS
        now: 当前时间（方便测试注入），默认 datetime.now()

    Returns:
        检查结果列表
    """
    db_path = db_path or SIM_DB_PATH
    thresholds = thresholds or DATA_SOURCE_THRESHOLDS
    now = now or datetime.now()

    checks = [
        (check_sim_positions, "sim_positions"),
        (check_sim_daily_nav, "sim_daily_nav"),
        (check_strategy_shadow_signals, "strategy_shadow_signals"),
        (check_watchlist_history, "watchlist_history"),
    ]

    results = []
    for check_fn, key in checks:
        thresh = thresholds.get(key, DEFAULT_FRESHNESS_HOURS)
        result = check_fn(db_path, thresh, now)
        results.append(result)

    return results


def format_report(
    results: List[Dict[str, Any]],
    check_time: Optional[str] = None,
) -> str:
    """生成人类可读的文本报告。"""
    check_time = check_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ok_count = sum(1 for r in results if r.get("ok"))
    fail_count = len(results) - ok_count

    lines = [
        "=" * 60,
        f"数据新鲜度监控报告 — {check_time}",
        f"检查 {len(results)} 项: ✅ {ok_count} 正常, ❌ {fail_count} 异常",
        "=" * 60,
    ]
    for r in results:
        icon = "✅" if r.get("ok") else "❌"
        lines.append(f"  {icon} {r.get('message', '?')}")
    lines.append("=" * 60)
    return "\n".join(lines)


def main() -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="数据新鲜度监控 (REQ-067)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/data_freshness_monitor.py           # 运行检查并输出文本报告
  python scripts/data_freshness_monitor.py --json    # 输出 JSON 结果到 stdout
  python scripts/data_freshness_monitor.py --quiet    # 静默模式（仅异常时输出）
  python scripts/data_freshness_monitor.py --notify   # 异常时推送企微通知
  python scripts/data_freshness_monitor.py --save-alerts  # 保存到 PM alerts 表
""",
    )
    parser.add_argument(
        "--json", action="store_true", help="输出 JSON 结果到 stdout"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="静默模式，仅异常时输出"
    )
    parser.add_argument(
        "--notify", action="store_true", help="异常时推送企微通知"
    )
    parser.add_argument(
        "--save-alerts", action="store_true",
        help="将结果保存到 freshness_alerts 表 (data/ops_runtime.db)"
    )
    parser.add_argument(
        "--db", type=str, default=None,
        help=f"sim_live_mirror.db 路径（默认: {SIM_DB_PATH}）"
    )
    parser.add_argument(
        "--pm-db", type=str, default=None,
        help=f"运行态告警库路径（默认: {PM_DB_PATH}；已不再使用 pm.db）"
    )
    parser.add_argument(
        "--threshold", type=int, default=DEFAULT_FRESHNESS_HOURS,
        help=f"新鲜度阈值，单位小时（默认: {DEFAULT_FRESHNESS_HOURS}h）"
    )
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else SIM_DB_PATH
    thresholds = dict.fromkeys(DATA_SOURCE_THRESHOLDS.keys(), args.threshold)
    now = datetime.now()
    check_time = now.strftime("%Y-%m-%d %H:%M:%S")

    # 运行检查
    results = run_all_checks(db_path, thresholds, now)

    # 保存到 PM alerts 表
    if args.save_alerts:
        pm_db = Path(args.pm_db) if args.pm_db else PM_DB_PATH
        save_alerts_to_pm(pm_db, results, check_time)

    # 推送通知
    if args.notify:
        notify_alerts(results, check_time)

    # 输出结果
    if args.json:
        output = {
            "check_time": check_time,
            "threshold_hours": args.threshold,
            "db_path": str(db_path),
            "results": results,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.quiet:
        failed = [r for r in results if not r.get("ok")]
        if failed:
            print(format_report(results, check_time))
    else:
        print(format_report(results, check_time))

    # 保存报告文件
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_data = {
        "check_time": check_time,
        "threshold_hours": args.threshold,
        "db_path": str(db_path),
        "results": results,
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    # 退出码：有失败项则非零
    has_failures = any(not r.get("ok") for r in results)
    return 1 if has_failures else 0


# ══════════════════════════════════════════════════════════════════════
# daily_check 集成接口
# ══════════════════════════════════════════════════════════════════════

def check_freshness_for_daily(
    db_path: Optional[Path] = None,
    thresholds: Optional[Dict[str, int]] = None,
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """
    供 daily_check / ops_daily_check 调用的集成接口。

    Returns:
        (ok: bool, summary: str, results: list)
        - ok: True 表示所有数据源新鲜
        - summary: 一行摘要文字
        - results: 详细结果列表
    """
    results = run_all_checks(db_path, thresholds)
    ok_count = sum(1 for r in results if r.get("ok"))
    fail_count = len(results) - ok_count
    ok = fail_count == 0
    summary = f"数据新鲜度: ✅ {ok_count}/{len(results)} 正常" if ok else \
              f"数据新鲜度: ❌ {fail_count}/{len(results)} 异常"
    return ok, summary, results


if __name__ == "__main__":
    sys.exit(main())
