#!/usr/bin/env python3
"""
scripts/qmt_diagnostic.py — QMT mini 零成交根因排查工具

用于诊断 BUG-013：QMT mini 账户（90072426）长期零成交的问题。

核心目标不是“盲目真下单”，而是把链路拆清楚：
1. 配置是否指向 QMT mini 账户而非真实账户；
2. xtquant / QMT 客户端是否可用；
3. 最近是否有 QMT 委托提交记录（sim_orders）；
4. 最近是否有 QMT 成交回调记录（sim_trades）；
5. 当前运行配置是否仍是 dry_run / sim-only，导致 QMT 永远静默。

使用方法：
    python scripts/qmt_diagnostic.py
    python scripts/qmt_diagnostic.py --push-wecom
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# 添加项目根目录到 sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from notifier.wecom_notifier import get_default_notifier

logger = logging.getLogger(__name__)

# QMT mini 账户 ID
QMT_MINI_ACCOUNT = "90072426"

# 禁止连接的真实账户
FORBIDDEN_ACCOUNTS = {"8890461376"}


def _safe_load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        return {"_load_error": str(exc)}


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        return {"_load_error": str(exc)}


def _detect_qmt_process() -> str:
    """返回 QMT 客户端进程状态；Windows 下尽量宽松匹配不同券商进程名。"""
    if os.name != "nt":
        return "非 Windows，跳过进程检查"
    try:
        proc = subprocess.run(
            ["tasklist", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        hay = proc.stdout.lower()
        # 不同 mini-QMT 发行包进程名差异较大；保守匹配常见关键字。
        needles = ["qmt", "xtminiqmt", "xttrader", "国金qmt"]
        return "运行中" if any(n in hay for n in needles) else "未运行"
    except Exception as exc:  # noqa: BLE001
        return f"检查失败: {exc}"


class QMTDiagnostic:
    """QMT 诊断工具"""

    def __init__(self, push_wecom: bool = False):
        self.push_wecom = push_wecom
        self.notifier = get_default_notifier() if push_wecom else None
        self.config_yaml = _safe_load_yaml(ROOT / "config.yaml")
        self.config_local = _safe_load_yaml(ROOT / "config.local.yaml")
        self.gateway_cfg = _safe_load_json(ROOT / "gateways" / "qmt_config.json")
        self.live_cfg = (self.config_local.get("broker") or {}).get("live") or {}
        self.diagnostic_results: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "account_id": QMT_MINI_ACCOUNT,
            "checks": {},
            "issues": [],
            "recommendations": [],
        }

    def _cfg_value(self, *names: str, default: Any = None) -> Any:
        """从 config.local broker.live → gateways/qmt_config.json 依次取配置。"""
        for source in (self.live_cfg, self.gateway_cfg):
            for name in names:
                value = source.get(name)
                if value not in (None, ""):
                    return value
        return default

    def check_qmt_connection(self) -> dict:
        """检查 QMT 连接前置条件（不发起下单）。"""
        print("\n🔍 检查 1/4：QMT 经纪商连接前置条件")
        result = {"status": "unknown", "details": {}, "issues": [], "passed": False}

        qmt_path = self._cfg_value("qmt_path")
        qmt_account = str(self._cfg_value("qmt_account", "account_id", default=""))
        session_id = self._cfg_value("session_id", default="未配置")
        xt_site = self._cfg_value("xtquant_site_packages")

        result["details"].update(
            {
                "qmt_path": qmt_path or "未配置",
                "qmt_path_exists": bool(qmt_path and Path(qmt_path).exists()),
                "account": qmt_account or "未配置",
                "session_id": session_id,
                "xtquant_site_packages": xt_site or "未配置",
                "xtquant_site_packages_exists": bool(xt_site and Path(xt_site).exists()),
            }
        )

        if not qmt_path or not Path(qmt_path).exists():
            result["issues"].append("QMT userdata 路径未配置或不存在")
        if not qmt_account:
            result["issues"].append("QMT 账户未配置")
        elif qmt_account != QMT_MINI_ACCOUNT:
            result["issues"].append(f"QMT 账户为 {qmt_account}，不是 mini 测试账户 {QMT_MINI_ACCOUNT}")
        if qmt_account in FORBIDDEN_ACCOUNTS:
            result["issues"].append(f"危险：配置指向真实账户 {qmt_account}，必须阻断")

        # 尝试导入 xtquant；如果主环境没有，自动临时加入 QMT 自带 site-packages 再试。
        try:
            if xt_site and Path(xt_site).exists() and str(xt_site) not in sys.path:
                sys.path.insert(0, str(xt_site))
            import xtquant  # noqa: F401

            result["details"]["xtquant"] = "可导入"
        except ImportError as exc:
            result["details"]["xtquant"] = f"不可导入: {exc}"
            result["issues"].append("xtquant 不可导入（需配置 QMT 自带 site-packages 或安装依赖）")

        qmt_proc = _detect_qmt_process()
        result["details"]["qmt_client"] = qmt_proc
        if qmt_proc == "未运行":
            result["issues"].append("QMT 客户端未运行，无法真实查询/下单")

        result["passed"] = not result["issues"]
        result["status"] = "passed" if result["passed"] else "failed"
        self._print_check_result("检查 1/4", result)
        self.diagnostic_results["checks"]["qmt_connection"] = result
        return result

    def check_order_submission(self) -> dict:
        """检查最近 7 天 QMT 委托提交和成交回调情况。"""
        print("\n🔍 检查 2/4：QMT 委托提交与成交回调")
        result = {"status": "unknown", "details": {}, "issues": [], "passed": False}
        since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        db_file = ROOT / "data" / "sim_live_mirror.db"
        result["details"]["db"] = str(db_file)
        result["details"]["since"] = since

        if not db_file.exists():
            result["status"] = "failed"
            result["issues"].append("sim_live_mirror.db 不存在")
            self._print_check_result("检查 2/4", result)
            self.diagnostic_results["checks"]["order_submission"] = result
            return result

        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        try:
            # 提交层：sim_orders（BUG-013 修复后会记录 qmt/qmt_dry_run）
            order_cols = {r[1] for r in conn.execute("PRAGMA table_info(sim_orders)").fetchall()}
            if order_cols:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN broker='qmt' THEN 1 ELSE 0 END) AS qmt_live,
                           SUM(CASE WHEN broker='qmt_dry_run' THEN 1 ELSE 0 END) AS qmt_dry,
                           SUM(CASE WHEN status LIKE '%TRADED%' THEN 1 ELSE 0 END) AS traded
                      FROM sim_orders
                     WHERE COALESCE(order_time, created_at) >= ?
                       AND broker IN ('qmt', 'qmt_dry_run')
                    """,
                    (since,),
                ).fetchone()
                result["details"]["qmt_order_submissions_7d"] = int(row["total"] or 0)
                result["details"]["qmt_live_submissions_7d"] = int(row["qmt_live"] or 0)
                result["details"]["qmt_dry_run_submissions_7d"] = int(row["qmt_dry"] or 0)
                result["details"]["qmt_order_traded_status_7d"] = int(row["traded"] or 0)
            else:
                result["details"]["qmt_order_submissions_7d"] = 0
                result["issues"].append("sim_orders 表不存在，无法判断 QMT 是否有提交层留痕")

            # 成交层：sim_trades（真实成交回调写 broker='qmt'）
            trade_cols = {r[1] for r in conn.execute("PRAGMA table_info(sim_trades)").fetchall()}
            date_expr = "COALESCE(created_at, trade_date)"
            if "created_at" not in trade_cols:
                date_expr = "trade_date"
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN broker='qmt' THEN 1 ELSE 0 END) AS qmt_fills,
                       SUM(CASE WHEN broker IN ('sim','live_mirror') THEN 1 ELSE 0 END) AS sim_like_fills
                  FROM sim_trades
                 WHERE {date_expr} >= ?
                """,
                (since,),
            ).fetchone()
            result["details"]["all_fills_7d"] = int(row["total"] or 0)
            result["details"]["qmt_fills_7d"] = int(row["qmt_fills"] or 0)
            result["details"]["sim_like_fills_7d"] = int(row["sim_like_fills"] or 0)
        finally:
            conn.close()

        qmt_submits = result["details"].get("qmt_order_submissions_7d", 0)
        qmt_live_submits = result["details"].get("qmt_live_submissions_7d", 0)
        qmt_dry_submits = result["details"].get("qmt_dry_run_submissions_7d", 0)
        qmt_fills = result["details"].get("qmt_fills_7d", 0)
        sim_like = result["details"].get("sim_like_fills_7d", 0)

        if qmt_fills > 0:
            result["status"] = "passed"
            result["passed"] = True
        elif qmt_live_submits > 0:
            result["status"] = "warning"
            result["passed"] = True
            result["issues"].append("有 QMT 真实委托提交但无成交回调，请检查委托状态/价格/回调链路")
        elif qmt_dry_submits > 0:
            result["status"] = "failed"
            result["issues"].append("只有 qmt_dry_run 提交记录，没有真实 QMT 委托")
        elif sim_like > 0:
            result["status"] = "failed"
            result["issues"].append("sim/live_mirror 有成交，但 QMT 提交层为 0：信号未路由到 QMT")
        else:
            result["status"] = "failed"
            result["issues"].append("最近 7 天既无 QMT 提交，也无本地成交，需先确认策略是否运行")

        if qmt_submits == 0:
            result["issues"].append("QMT 委托提交留痕为 0（旧版本会静默，已在 broker 层补 sim_orders 留痕）")

        self._print_check_result("检查 2/4", result)
        self.diagnostic_results["checks"]["order_submission"] = result
        return result

    def check_signals_consistency(self) -> dict:
        """检查信号/调度输入是否足够驱动 QMT 分流。"""
        print("\n🔍 检查 3/4：信号与分流输入")
        result = {"status": "unknown", "details": {}, "issues": [], "passed": False}

        daily_signals = ROOT / "data" / "daily_signals.json"
        alert_state = ROOT / "output" / "alert_state.json"
        dispatch_logs = sorted((ROOT / "output").glob("fusion_dispatch_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

        result["details"]["daily_signals_exists"] = daily_signals.exists()
        result["details"]["alert_state_exists"] = alert_state.exists()
        result["details"]["latest_dispatch_log"] = str(dispatch_logs[0]) if dispatch_logs else "无"

        if daily_signals.exists():
            try:
                doc = json.loads(daily_signals.read_text(encoding="utf-8"))
                result["details"]["daily_signals_count"] = len(doc.get("signals", []))
                result["details"]["daily_signals_trading_date"] = doc.get("trading_date")
            except Exception as exc:  # noqa: BLE001
                result["issues"].append(f"daily_signals.json 解析失败: {exc}")
        else:
            result["issues"].append("缺少 data/daily_signals.json，fusion_dispatch 无 AI 信号输入")

        if dispatch_logs:
            try:
                log = json.loads(dispatch_logs[0].read_text(encoding="utf-8"))
                result["details"]["latest_qmt_decisions"] = len(log.get("qmt_decisions", []))
                result["details"]["latest_qmt_results"] = len(log.get("qmt_results", []))
                result["details"]["latest_qmt_dry_run"] = log.get("qmt_dry_run")
                if log.get("qmt_dry_run"):
                    result["issues"].append("最近 fusion_dispatch 日志显示 qmt_dry_run=True")
            except Exception as exc:  # noqa: BLE001
                result["issues"].append(f"最新 dispatch 日志解析失败: {exc}")
        else:
            result["issues"].append("缺少 fusion_dispatch 日志，无法证明 QMT 分流调度运行过")

        # 信号存在 + 调度日志存在即说明输入链路基本可追踪；dry_run/无决策作为 warning/failed。
        if daily_signals.exists() and dispatch_logs:
            result["passed"] = not any("dry_run=True" in x for x in result["issues"])
            result["status"] = "passed" if result["passed"] else "warning"
        else:
            result["status"] = "failed"

        self._print_check_result("检查 3/4", result)
        self.diagnostic_results["checks"]["signals_consistency"] = result
        return result

    def check_live_mirror_config(self) -> dict:
        """检查 live_mirror / broker.live 配置是否会导致 QMT 静默。"""
        print("\n🔍 检查 4/4：live_mirror / broker.live 配置")
        result = {"status": "unknown", "details": {}, "issues": [], "passed": False}

        broker_cfg = self.config_yaml.get("broker") or {}
        local_broker = self.config_local.get("broker") or {}
        learn_cfg = (self.config_yaml.get("accounts") or {}).get("learn") or {}
        live_cfg = self.live_cfg

        result["details"].update(
            {
                "config_yaml_broker_mode": broker_cfg.get("mode", "未配置"),
                "config_local_broker_mode": local_broker.get("mode", "未配置"),
                "learn_auto_trade": learn_cfg.get("auto_trade", "未配置"),
                "live_qmt_account": live_cfg.get("qmt_account", "未配置"),
                "live_qmt_path_configured": bool(live_cfg.get("qmt_path")),
                "live_dry_run": live_cfg.get("dry_run", "未配置"),
                "legacy_live_mirror": self.config_yaml.get("live_mirror"),
            }
        )

        if not learn_cfg.get("auto_trade"):
            result["issues"].append("accounts.learn.auto_trade 未开启，学习账户不会自动交易")
        if str(live_cfg.get("qmt_account", "")) != QMT_MINI_ACCOUNT:
            result["issues"].append("config.local.yaml broker.live.qmt_account 未指向 90072426")
        if not live_cfg.get("qmt_path"):
            result["issues"].append("config.local.yaml broker.live.qmt_path 未配置")
        if bool(live_cfg.get("dry_run", True)):
            result["issues"].append("config.local.yaml broker.live.dry_run=True，QMT 下单被显式禁用")
        if broker_cfg.get("mode") == "sim" and local_broker.get("mode") == "sim":
            result["issues"].append("全局 broker.mode 仍为 sim；只有显式 fusion_dispatch QMT 分流才会触达 QMT")

        result["passed"] = not result["issues"]
        result["status"] = "passed" if result["passed"] else "failed"
        self._print_check_result("检查 4/4", result)
        self.diagnostic_results["checks"]["live_mirror_config"] = result
        return result

    @staticmethod
    def _print_check_result(label: str, result: dict) -> None:
        status_icon = "✅" if result.get("passed") else ("⚠️" if result.get("status") == "warning" else "❌")
        print(f"{status_icon} {label} 结果：{result['status']}")
        for key, value in result.get("details", {}).items():
            print(f"   - {key}: {value}")
        for issue in result.get("issues", []):
            print(f"   - 问题：{issue}")

    def generate_report(self) -> str:
        """生成诊断报告"""
        print("\n📊 生成诊断报告...")

        report_lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "📋 BUG-013 QMT mini 零成交诊断报告",
            f"⏰ {self.diagnostic_results['timestamp']}",
            f"🏦 账户：{self.diagnostic_results['account_id']}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        for check_name, check_result in self.diagnostic_results["checks"].items():
            status_icon = "✅" if check_result.get("passed") else ("⚠️" if check_result.get("status") == "warning" else "❌")
            report_lines.append(f"{status_icon} {check_name}: {check_result['status']}")
            for issue in check_result.get("issues", []):
                report_lines.append(f"   - {issue}")

        report_lines.append("")
        report_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        report_lines.append("🔬 当前根因判断：")

        root_causes: list[str] = []
        live_cfg_check = self.diagnostic_results["checks"].get("live_mirror_config", {})
        order_check = self.diagnostic_results["checks"].get("order_submission", {})
        conn_check = self.diagnostic_results["checks"].get("qmt_connection", {})

        live_issues = "；".join(live_cfg_check.get("issues", []))
        order_issues = "；".join(order_check.get("issues", []))
        conn_issues = "；".join(conn_check.get("issues", []))
        if "dry_run=True" in live_issues:
            root_causes.append("配置层 dry_run=True，QMT 真实下单被禁用")
        if "QMT 提交层为 0" in order_issues or "未路由到 QMT" in order_issues:
            root_causes.append("执行链路只写 sim/live_mirror，本地无 QMT 委托提交留痕")
        if "客户端未运行" in conn_issues:
            root_causes.append("QMT 客户端未运行，无法真实连接/查询/下单")
        if "全局 broker.mode 仍为 sim" in live_issues:
            root_causes.append("全局 broker.mode=sim，必须依赖 fusion_dispatch 显式分流到 QMT")

        if root_causes:
            for item in root_causes:
                report_lines.append(f"   - {item}")
        else:
            report_lines.append("   - 未发现阻断性配置；若仍零成交，请检查 QMT 委托/成交回调日志")

        report_lines.append("")
        report_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        report_lines.append("🛠️ 本次修复：")
        report_lines.append("   1. broker/qmt_broker.py 增加 sim_orders 提交层留痕（qmt/qmt_dry_run 都记录）")
        report_lines.append("   2. 修正 QMT 成交回调落库字段：direction / broker_order_id，避免旧字段 side/order_id 写入失败")
        report_lines.append("   3. qmt_diagnostic.py 增强配置、dry_run、提交层、成交层与调度日志诊断")
        report_lines.append("")
        report_lines.append("💡 下一步：")
        report_lines.append("   - 若要恢复 QMT mini 真实模拟下单：先手动启动 QMT mini 并登录 90072426，再把 config.local.yaml broker.live.dry_run 改为 false")
        report_lines.append("   - 继续保持真实账户 8890461376 硬隔离，禁止自动连接")
        report_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        report = "\n".join(report_lines)
        print(report)
        return report

    def run_all_checks(self) -> str:
        """运行所有检查并生成报告"""
        print("🚀 开始 BUG-013 QMT 诊断...")
        print(f"🏦 账户：{QMT_MINI_ACCOUNT}")

        self.check_qmt_connection()
        self.check_order_submission()
        self.check_signals_consistency()
        self.check_live_mirror_config()

        report = self.generate_report()

        report_file = ROOT / f"output/qmt_diagnostic_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(report, encoding="utf-8")
        print(f"\n💾 诊断报告已保存：{report_file}")

        if self.push_wecom and self.notifier:
            print("\n📤 推送诊断报告到企微...")
            ok = self.notifier.push_text(report)
            print("✅ 已推送" if ok else "❌ 推送失败")

        return report


def main() -> None:
    parser = argparse.ArgumentParser(description="QMT 诊断工具")
    parser.add_argument("--push-wecom", action="store_true", help="推送诊断报告到企微")
    args = parser.parse_args()

    diagnostic = QMTDiagnostic(push_wecom=args.push_wecom)
    diagnostic.run_all_checks()


if __name__ == "__main__":
    main()
