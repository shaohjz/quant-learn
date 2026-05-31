#!/usr/bin/env python3
"""
scripts/qmt_diagnostic.py — QMT mini 零成交根因排查工具

用于诊断 REQ-045：QMT mini 账户（90072426）始终零成交的问题

诊断项目：
1. 检测 QMT 经纪商连接状态
2. 检查订单是否成功提交但未成交
3. 对比 sim/live 信号是否一致
4. 生成诊断报告并推送企微

使用方法：
    python scripts/qmt_diagnostic.py
    python scripts/qmt_diagnostic.py --push-wecom  # 推送诊断报告到企微
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# 添加项目根目录到 sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from notifier.wecom_notifier import WecomNotifier, get_default_notifier

logger = logging.getLogger(__name__)

# QMT mini 账户 ID
QMT_MINI_ACCOUNT = "90072426"

# 禁止连接的真实账户
FORBIDDEN_ACCOUNTS = {"8890461376"}


class QMTDiagnostic:
    """QMT 诊断工具"""

    def __init__(self, push_wecom: bool = False):
        self.push_wecom = push_wecom
        self.notifier = get_default_notifier() if push_wecom else None
        self.diagnostic_results = {
            "timestamp": datetime.now().isoformat(),
            "account_id": QMT_MINI_ACCOUNT,
            "checks": {},
            "issues": [],
            "recommendations": [],
        }

    def check_qmt_connection(self) -> dict:
        """检查 QMT 连接状态"""
        print("\n🔍 检查 1/4：QMT 经纪商连接状态")
        result = {
            "status": "unknown",
            "details": {},
            "passed": False,
        }

        try:
            # 检查 QMT 配置文件
            config_path = ROOT / "gateways" / "qmt_config.json"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    qmt_config = json.load(f)
                result["details"]["config_file"] = "存在"
                result["details"]["qmt_path"] = qmt_config.get("qmt_path", "未配置")
                result["details"]["account_id"] = qmt_config.get("account_id", "未配置")
                result["details"]["session_id"] = qmt_config.get("session_id", "未配置")
            else:
                result["details"]["config_file"] = "不存在"
                result["issues"] = ["qmt_config.json 配置文件不存在"]

            # 尝试导入 xtquant
            try:
                import xtquant  # noqa: F401

                result["details"]["xtquant"] = "已安装"
            except ImportError:
                result["details"]["xtquant"] = "未安装"
                result["issues"] = ["xtquant 未安装，请检查 QMT 安装路径"]

            # 检查 QMT 客户端是否运行（通过进程检查 - Windows）
            if os.name == "nt":
                try:
                    import subprocess

                    result_proc = subprocess.run(
                        ["tasklist", "/FI", "IMAGENAME eq QMTClient.exe", "/NH"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if "QMTClient.exe" in result_proc.stdout:
                        result["details"]["qmt_client"] = "运行中"
                    else:
                        result["details"]["qmt_client"] = "未运行"
                        result["issues"] = ["QMT 客户端未运行，请先启动 QMT 并登录"]
                except Exception as e:
                    result["details"]["qmt_client"] = f"检查失败: {e}"

            # 判断检查是否通过
            if (
                result["details"].get("config_file") == "存在"
                and result["details"].get("xtquant") == "已安装"
                and result["details"].get("qmt_client") == "运行中"
            ):
                result["status"] = "passed"
                result["passed"] = True
            else:
                result["status"] = "failed"

        except Exception as e:
            result["status"] = "error"
            result["details"]["error"] = str(e)
            logger.exception("检查 QMT 连接时发生异常")

        # 打印结果
        status_icon = "✅" if result["passed"] else "❌"
        print(f"{status_icon} 检查 1/4 结果：{result['status']}")
        for key, value in result["details"].items():
            print(f"   - {key}: {value}")
        if result.get("issues"):
            print(f"   - 问题：{', '.join(result['issues'])}")

        self.diagnostic_results["checks"]["qmt_connection"] = result
        return result

    def check_order_submission(self) -> dict:
        """检查订单提交情况"""
        print("\n🔍 检查 2/4：订单提交与成交情况")
        result = {
            "status": "unknown",
            "details": {},
            "passed": False,
        }

        try:
            # 检查两个数据库中的 QMT 订单记录
            import sqlite3
            
            db_files = [
                ROOT / "data" / "sim.db",
                ROOT / "data" / "sim_live_mirror.db"
            ]
            
            total_qmt_orders = 0
            total_orders = 0
            
            for db_file in db_files:
                if not db_file.exists():
                    continue
                    
                conn = sqlite3.connect(str(db_file))
                cursor = conn.cursor()
                
                # 查询最近的订单（两个数据库都查）
                try:
                    cursor.execute(
                        """
                        SELECT COUNT(*) as total,
                               SUM(CASE WHEN broker='qmt' THEN 1 ELSE 0 END) as qmt_orders
                        FROM sim_trades
                        WHERE created_at >= datetime('now', '-7 days')
                        """
                    )
                    row = cursor.fetchone()
                    if row:
                        total_orders += row[0] or 0
                        total_qmt_orders += row[1] or 0
                except Exception as e:
                    logger.warning(f"查询 {db_file} 失败: {e}")
                
                conn.close()
            
            result["details"]["total_orders_7d"] = total_orders
            result["details"]["qmt_orders_7d"] = total_qmt_orders
            
            # 判断检查是否通过
            if total_qmt_orders > 0:
                result["status"] = "warning"
                result["issues"] = [f"找到 {total_qmt_orders} 个 QMT 订单记录，需检查是否成交"]
                result["passed"] = True  # 至少订单已提交
            else:
                result["status"] = "failed"
                result["issues"] = ["最近 7 天没有 QMT 订单记录"]

        except Exception as e:
            result["status"] = "error"
            result["details"]["error"] = str(e)
            logger.exception("检查订单提交时发生异常")

        # 打印结果
        status_icon = "✅" if result["passed"] else ("⚠️" if result["status"] == "warning" else "❌")
        print(f"{status_icon} 检查 2/4 结果：{result['status']}")
        for key, value in result["details"].items():
            print(f"   - {key}: {value}")
        if result.get("issues"):
            print(f"   - 问题：{', '.join(result['issues'])}")

        self.diagnostic_results["checks"]["order_submission"] = result
        return result

    def check_signals_consistency(self) -> dict:
        """检查 sim/live 信号一致性"""
        print("\n🔍 检查 3/4：sim/live 信号一致性")
        result = {
            "status": "unknown",
            "details": {},
            "passed": False,
        }

        try:
            # 读取最近的信号记录（从 logs 或 output 目录）
            signal_files = list((ROOT / "output").glob("signals_*.json"))
            signal_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

            if signal_files:
                latest_signal_file = signal_files[0]
                result["details"]["latest_signal_file"] = str(latest_signal_file)

                with open(latest_signal_file, "r", encoding="utf-8") as f:
                    signals = json.load(f)

                # 统计 sim 和 live 信号
                sim_signals = [s for s in signals if s.get("account_id") == "sim"]
                live_signals = [s for s in signals if s.get("account_id") == "live"]

                result["details"]["sim_signals_count"] = len(sim_signals)
                result["details"]["live_signals_count"] = len(live_signals)

                # 比较信号差异
                if sim_signals and live_signals:
                    sim_symbols = {s.get("symbol") for s in sim_signals}
                    live_symbols = {s.get("symbol") for s in live_signals}

                    common_symbols = sim_symbols & live_symbols
                    only_sim = sim_symbols - live_symbols
                    only_live = live_symbols - sim_symbols

                    result["details"]["common_signals"] = len(common_symbols)
                    result["details"]["only_in_sim"] = len(only_sim)
                    result["details"]["only_in_live"] = len(only_live)

                    if len(common_symbols) > 0:
                        result["status"] = "passed"
                        result["passed"] = True
                    else:
                        result["status"] = "warning"
                        result["issues"] = ["sim/live 信号无交集，可能配置不一致"]
                else:
                    result["status"] = "warning"
                    result["issues"] = ["sim 或 live 信号缺失，无法比较"]
            else:
                result["status"] = "failed"
                result["issues"] = ["未找到信号文件，请先运行策略生成信号"]

        except Exception as e:
            result["status"] = "error"
            result["details"]["error"] = str(e)
            logger.exception("检查信号一致性时发生异常")

        # 打印结果
        status_icon = "✅" if result["passed"] else ("⚠️" if result["status"] == "warning" else "❌")
        print(f"{status_icon} 检查 3/4 结果：{result['status']}")
        for key, value in result["details"].items():
            print(f"   - {key}: {value}")
        if result.get("issues"):
            print(f"   - 问题：{', '.join(result['issues'])}")

        self.diagnostic_results["checks"]["signals_consistency"] = result
        return result

    def check_live_mirror_config(self) -> dict:
        """检查 live_mirror 配置"""
        print("\n🔍 检查 4/4：live_mirror 配置检查")
        result = {
            "status": "unknown",
            "details": {},
            "passed": False,
        }

        try:
            # 检查 config.yaml 中的 live_mirror 配置
            import yaml

            config_path = ROOT / "config.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)

                live_mirror = config.get("live_mirror", {})
                result["details"]["live_mirror_enabled"] = live_mirror.get("enabled", False)
                result["details"]["live_mirror_account_id"] = live_mirror.get("account_id", "未配置")
                result["details"]["live_mirror_broker"] = live_mirror.get("broker", "未配置")

                # 检查是否连接到 QMT 实盘接口
                if live_mirror.get("enabled") and live_mirror.get("broker") == "qmt":
                    result["status"] = "passed"
                    result["passed"] = True
                elif live_mirror.get("enabled") and live_mirror.get("broker") != "qmt":
                    result["status"] = "warning"
                    result["issues"] = [f"live_mirror.broker = {live_mirror.get('broker')}，不是 qmt"]
                else:
                    result["status"] = "failed"
                    result["issues"] = ["live_mirror 未启用或配置不完整"]
            else:
                result["status"] = "failed"
                result["issues"] = ["config.yaml 不存在"]

        except Exception as e:
            result["status"] = "error"
            result["details"]["error"] = str(e)
            logger.exception("检查 live_mirror 配置时发生异常")

        # 打印结果
        status_icon = "✅" if result["passed"] else ("⚠️" if result["status"] == "warning" else "❌")
        print(f"{status_icon} 检查 4/4 结果：{result['status']}")
        for key, value in result["details"].items():
            print(f"   - {key}: {value}")
        if result.get("issues"):
            print(f"   - 问题：{', '.join(result['issues'])}")

        self.diagnostic_results["checks"]["live_mirror_config"] = result
        return result

    def generate_report(self) -> str:
        """生成诊断报告"""
        print("\n📊 生成诊断报告...")

        report_lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "📋 QMT 诊断报告",
            f"⏰ {self.diagnostic_results['timestamp']}",
            f"🏦 账户：{self.diagnostic_results['account_id']}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        # 汇总检查结果
        all_passed = True
        for check_name, check_result in self.diagnostic_results["checks"].items():
            status_icon = "✅" if check_result["passed"] else ("⚠️" if check_result["status"] == "warning" else "❌")
            report_lines.append(f"{status_icon} {check_name}: {check_result['status']}")
            if check_result.get("issues"):
                for issue in check_result["issues"]:
                    report_lines.append(f"   - ⚠️ {issue}")
            if not check_result["passed"]:
                all_passed = False

        report_lines.append("")
        report_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # 根因分析
        report_lines.append("🔬 根因分析：")
        issues = []
        if not self.diagnostic_results["checks"].get("qmt_connection", {}).get("passed"):
            issues.append("QMT 连接异常（客户端未启动/xtquant 未安装/配置缺失）")
        if not self.diagnostic_results["checks"].get("order_submission", {}).get("passed"):
            issues.append("订单未提交或未成交（可能 dry_run=True 或 QMT 接口异常）")
        if not self.diagnostic_results["checks"].get("signals_consistency", {}).get("passed"):
            issues.append("sim/live 信号不一致（可能配置或策略逻辑差异）")
        if not self.diagnostic_results["checks"].get("live_mirror_config", {}).get("passed"):
            issues.append("live_mirror 配置异常（未启用 broker 或 broker ≠ qmt）")

        if issues:
            for issue in issues:
                report_lines.append(f"   - {issue}")
        else:
            report_lines.append("   - 所有检查通过，建议检查 QMT 客户端日志")

        report_lines.append("")
        report_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # 建议
        report_lines.append("💡 建议：")
        recommendations = [
            "1. 确认 QMT 客户端已启动并登录成功",
            "2. 检查 config.yaml 中 live_mirror.broker = qmt",
            "3. 检查 gateways/qmt_config.json 配置是否正确",
            "4. 确认 dry_run = False 以实际下单",
            "5. 检查 QMT 客户端日志（userdata_mini/logs/）",
        ]
        for rec in recommendations:
            report_lines.append(f"   {rec}")

        report_lines.append("")
        report_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        report = "\n".join(report_lines)
        print(report)

        return report

    def run_all_checks(self) -> str:
        """运行所有检查并生成报告"""
        print("🚀 开始 QMT 诊断...")
        print(f"🏦 账户：{QMT_MINI_ACCOUNT}")

        # 运行所有检查
        self.check_qmt_connection()
        self.check_order_submission()
        self.check_signals_consistency()
        self.check_live_mirror_config()

        # 生成报告
        report = self.generate_report()

        # 保存到文件
        report_file = ROOT / f"output/qmt_diagnostic_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n💾 诊断报告已保存：{report_file}")

        # 推送到企微
        if self.push_wecom and self.notifier:
            print("\n📤 推送诊断报告到企微...")
            self.notifier.push_text(report)
            print("✅ 已推送")

        return report


def main():
    parser = argparse.ArgumentParser(description="QMT 诊断工具")
    parser.add_argument("--push-wecom", action="store_true", help="推送诊断报告到企微")
    args = parser.parse_args()

    diagnostic = QMTDiagnostic(push_wecom=args.push_wecom)
    diagnostic.run_all_checks()


if __name__ == "__main__":
    main()
