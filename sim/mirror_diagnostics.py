"""
sim/mirror_diagnostics.py
双账户执行一致性诊断与镜像差异归因 (REQ-034)

功能：
  1. 对比 sim_account (模拟盘) 与 QMT live 账户的持仓、成交、现金差异
  2. 对差异进行原因分类（未开启实盘、风控拦截、下单失败、同步延迟、账户配置差异等）
  3. 给出下一步处理建议
  4. 输出结构化诊断报告（Markdown + JSON）

诊断维度：
  - 持仓差异：sim 有持仓但 live 为空
  - 成交差异：sim 有成交记录但 live 没有
  - 现金利用率差异：sim 已全仓但 live 仍全现金
  - 个股差异：同一只股票在两边状态不同

原因分类：
  - not_started: 实盘未开启 / QMT 未登录
  - risk_blocked: 风控拦截（仓位超限、单笔超限、日内预算用尽）
  - order_failed: 下单失败（资金不足、持仓不足、系统拒绝）
  - sync_delay: 同步延迟（订单已发出但未成交/确认）
  - config_mismatch: 账户配置差异（初始资金不同、风控参数不同）
  - broker_rejected: 券商/交易所拒绝（价格偏离、涨跌停、停牌）
  - timeout: 订单超时未成交
  - partial_fill: 部分成交（sim 全成但 live 部分成）
"""

from __future__ import annotations
import os
import json
import logging
from datetime import date, datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================
# 数据结构
# ============================================================

@dataclass
class DiagIssue:
    """单条诊断问题"""
    issue_type: str           # 问题类型：position_mismatch / trade_mismatch / cash_mismatch
    severity: str             # 严重度：critical / warning / info
    stock_code: str = ""     # 关联股票代码（如适用）
    stock_name: str = ""     # 关联股票名称
    sim_value: str = ""      # 模拟盘值
    live_value: str = ""     # 实盘值
    reason: str = ""         # 原因分类
    suggestion: str = ""     # 处理建议
    detail: str = ""         # 详细说明


@dataclass
class DiagReport:
    """完整诊断报告"""
    trade_date: str
    generated_at: str
    sim_account_id: int = 1
    live_account_id: int = 2
    
    # 概览
    total_issues: int = 0
    critical_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    
    # 差异摘要
    position_diff_count: int = 0   # 持仓差异数
    trade_diff_count: int = 0      # 成交差异数
    cash_diff_pct: float = 0.0     # 现金利用率差异
    
    # 原因分布
    reason_distribution: dict = field(default_factory=dict)
    
    # 详细问题列表
    issues: list = field(default_factory=list)
    
    # 诊断结论
    conclusion: str = ""
    action_items: list = field(default_factory=list)


# ============================================================
# 核心诊断器
# ============================================================

class MirrorDiagnostics:
    """双账户一致性诊断器"""
    
    def __init__(self, db_path: str = None, sim_account_id: int = 1, live_account_id: int = 2):
        """
        Args:
            db_path: 数据库路径，默认使用 sim_live_mirror.db
            sim_account_id: 模拟盘账户 ID（默认 1）
            live_account_id: 实盘账户 ID（默认 2，对应 real_portfolio）
        """
        self.db_path = db_path or self._get_default_db_path()
        self.sim_account_id = sim_account_id
        self.live_account_id = live_account_id
        
    def _get_default_db_path(self) -> str:
        ROOT = Path(__file__).resolve().parents[1]
        return str(ROOT / "data" / "sim_live_mirror.db")
        
    def _get_conn(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _fetch_account(self, conn, account_id: int) -> Optional[dict]:
        cur = conn.cursor()
        row = cur.execute('SELECT * FROM sim_account WHERE id=?', (account_id,)).fetchone()
        return dict(row) if row else None
    
    def _fetch_positions(self, conn, account_id: int) -> list[dict]:
        cur = conn.cursor()
        rows = cur.execute(
            'SELECT * FROM sim_positions WHERE account_id=? AND quantity > 0 ORDER BY market_value DESC',
            (account_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    
    def _fetch_trades(self, conn, account_id: int, target_date: str) -> list[dict]:
        cur = conn.cursor()
        rows = cur.execute(
            'SELECT * FROM sim_trades WHERE account_id=? AND trade_date=? ORDER BY id',
            (account_id, target_date)
        ).fetchall()
        return [dict(r) for r in rows]
    
    def _fetch_orders(self, conn, account_id: int, target_date: str) -> list[dict]:
        cur = conn.cursor()
        rows = cur.execute(
            'SELECT * FROM sim_orders WHERE account_id=? AND DATE(order_time)=? ORDER BY order_time',
            (account_id, target_date)
        ).fetchall()
        return [dict(r) for r in rows]
    
    # ========================================
    # 诊断方法
    # ========================================
    
    def diagnose(self, target_date: str = None) -> DiagReport:
        """
        执行完整诊断，返回诊断报告
        
        Args:
            target_date: 诊断日期（YYYY-MM-DD），默认今天
        """
        target_date = target_date or date.today().isoformat()
        
        report = DiagReport(
            trade_date=target_date,
            generated_at=datetime.now().isoformat(),
        )
        
        conn = self._get_conn()
        try:
            sim_acct = self._fetch_account(conn, self.sim_account_id)
            live_acct = self._fetch_account(conn, self.live_account_id)
            
            if not sim_acct:
                report.conclusion = "⚠️ 模拟盘账户不存在，无法执行诊断"
                return report
            
            if not live_acct:
                report.conclusion = "⚠️ 实盘账户不存在，请先初始化实盘账户（id=2）"
                report.issues.append({
                    "issue_type": "account_missing",
                    "severity": "critical",
                    "reason": "not_initialized",
                    "suggestion": "运行 init_live_mirror.py 初始化实盘镜像账户",
                    "detail": "实盘账户（id=2）在数据库中不存在。这可能是因为还未运行过实盘同步脚本。"
                })
                report.total_issues = 1
                report.critical_count = 1
                return report
            
            # 1. 诊断账户层面差异
            self._diagnose_account(report, sim_acct, live_acct)
            
            # 2. 诊断持仓差异
            self._diagnose_positions(report, conn, target_date)
            
            # 3. 诊断成交差异
            self._diagnose_trades(report, conn, target_date)
            
            # 4. 诊断订单状态（查找失败/拒绝的订单）
            self._diagnose_orders(report, conn, target_date)
            
            # 5. 生成结论和行动项
            self._generate_conclusion(report)
            
        finally:
            conn.close()
        
        return report
    
    def _diagnose_account(self, report: DiagReport, sim_acct: dict, live_acct: dict):
        """诊断账户层面差异（现金、总资产）"""
        sim_cash = float(sim_acct.get('cash') or 0)
        live_cash = float(live_acct.get('cash') or 0)
        sim_total = float(sim_acct.get('total_value') or 0)
        live_total = float(live_acct.get('total_value') or 0)
        sim_initial = float(sim_acct.get('initial_cash') or 1)
        live_initial = float(live_acct.get('initial_cash') or 1)
        
        # 现金利用率差异
        sim_cash_ratio = 1.0 - (sim_cash / sim_total) if sim_total > 0 else 1.0
        live_cash_ratio = 1.0 - (live_cash / live_total) if live_total > 0 else 0.0
        cash_diff = abs(sim_cash_ratio - live_cash_ratio)
        report.cash_diff_pct = round(cash_diff * 100, 2)
        
        if cash_diff > 0.3:  # 仓位差异 > 30%
            issue = {
                "issue_type": "cash_mismatch",
                "severity": "critical" if cash_diff > 0.8 else "warning",
                "sim_value": f"现金 ¥{sim_cash:,.0f}（仓位 {sim_cash_ratio*100:.1f}%）",
                "live_value": f"现金 ¥{live_cash:,.0f}（仓位 {live_cash_ratio*100:.1f}%）",
                "reason": "not_started" if live_cash_ratio < 0.05 else "risk_blocked",
                "suggestion": "检查实盘是否开启自动交易，或查看风控是否拦截了所有买入",
                "detail": f"模拟盘仓位 {sim_cash_ratio*100:.1f}%，实盘仓位 {live_cash_ratio*100:.1f}%，差异 {cash_diff*100:.1f}%"
            }
            if live_cash_ratio < 0.05:
                issue["reason"] = "not_started"
                issue["suggestion"] = "实盘可能未开启自动买入，或 QMT 未登录/未运行策略"
            report.issues.append(issue)
            
        # 初始资金差异
        if abs(sim_initial - live_initial) > 1:
            report.issues.append({
                "issue_type": "config_mismatch",
                "severity": "info",
                "sim_value": f"初始资金 ¥{sim_initial:,.0f}",
                "live_value": f"初始资金 ¥{live_initial:,.0f}",
                "reason": "config_mismatch",
                "suggestion": "确认双账户初始资金配置是否一致",
                "detail": "双账户初始资金不同，可能导致仓位计算结果不一致"
            })
    
    def _diagnose_positions(self, report: DiagReport, conn, target_date: str):
        """诊断持仓差异"""
        sim_pos = self._fetch_positions(conn, self.sim_account_id)
        live_pos = self._fetch_positions(conn, self.live_account_id)
        
        sim_pos_dict = {p['stock_code']: p for p in sim_pos}
        live_pos_dict = {p['stock_code']: p for p in live_pos}
        
        # 找出 sim 有但 live 没有的持仓
        sim_only = set(sim_pos_dict.keys()) - set(live_pos_dict.keys())
        # 找出 live 有但 sim 没有的持仓
        live_only = set(live_pos_dict.keys()) - set(sim_pos_dict.keys())
        # 找出两边都有的持仓
        common = set(sim_pos_dict.keys()) & set(live_pos_dict.keys())
        
        report.position_diff_count = len(sim_only) + len(live_only)
        
        for code in sim_only:
            p = sim_pos_dict[code]
            issue = {
                "issue_type": "position_mismatch",
                "severity": "critical",
                "stock_code": code,
                "stock_name": p.get('stock_name', ''),
                "sim_value": f"{p['quantity']}股 @¥{float(p.get('avg_cost', 0)):.2f} 市值¥{float(p.get('market_value', 0)):.0f}",
                "live_value": "空仓",
                "reason": "not_started",
                "suggestion": "检查实盘 QMT 是否开启了自动交易，或查看订单是否被拒绝",
                "detail": f"模拟盘已建仓 {p['quantity']} 股，但实盘无此持仓"
            }
            report.issues.append(issue)
        
        for code in live_only:
            p = live_pos_dict[code]
            issue = {
                "issue_type": "position_mismatch",
                "severity": "warning",
                "stock_code": code,
                "stock_name": p.get('stock_name', ''),
                "sim_value": "空仓",
                "live_value": f"{p['quantity']}股 @¥{float(p.get('avg_cost', 0)):.2f} 市值¥{float(p.get('market_value', 0)):.0f}",
                "reason": "config_mismatch",
                "suggestion": "检查模拟盘策略是否漏掉此股票，或实盘有手动操作",
                "detail": f"实盘有持仓但模拟盘没有，可能是手动操作或策略差异"
            }
            report.issues.append(issue)
        
        # 检查共同持仓的数量差异
        for code in common:
            sp = sim_pos_dict[code]
            lp = live_pos_dict[code]
            sq = int(sp['quantity'])
            lq = int(lp['quantity'])
            if sq != lq:
                diff_pct = abs(sq - lq) / max(sq, lq) * 100
                issue = {
                    "issue_type": "position_mismatch",
                    "severity": "warning" if diff_pct < 20 else "critical",
                    "stock_code": code,
                    "stock_name": sp.get('stock_name', ''),
                    "sim_value": f"{sq}股 @¥{float(sp.get('avg_cost', 0)):.2f}",
                    "live_value": f"{lq}股 @¥{float(lp.get('avg_cost', 0)):.2f}",
                    "reason": "partial_fill" if min(sq, lq) > 0 else "order_failed",
                    "suggestion": "检查订单成交情况，可能有部分成交或下单失败",
                    "detail": f"持仓数量差异 {abs(sq - lq)} 股（{diff_pct:.1f}%）"
                }
                report.issues.append(issue)
    
    def _diagnose_trades(self, report: DiagReport, conn, target_date: str):
        """诊断成交差异"""
        sim_trades = self._fetch_trades(conn, self.sim_account_id, target_date)
        live_trades = self._fetch_trades(conn, self.live_account_id, target_date)
        
        sim_trade_dict = {}  # (code, direction) -> list of trades
        for t in sim_trades:
            key = (t['stock_code'], t['direction'])
            sim_trade_dict.setdefault(key, []).append(t)
        
        live_trade_dict = {}
        for t in live_trades:
            key = (t['stock_code'], t['direction'])
            live_trade_dict.setdefault(key, []).append(t)
        
        # 找出 sim 有成交但 live 没有的
        for key, trades in sim_trade_dict.items():
            code, direction = key
            live_same = live_trade_dict.get(key, [])
            sim_qty = sum(int(t['quantity']) for t in trades)
            live_qty = sum(int(t['quantity']) for t in live_same)
            
            if live_qty == 0 and sim_qty > 0:
                # 完全没有对应的 live 成交
                t = trades[0]
                issue = {
                    "issue_type": "trade_mismatch",
                    "severity": "critical",
                    "stock_code": code,
                    "stock_name": t.get('stock_name', ''),
                    "sim_value": f"{direction} {sim_qty}股 @¥{float(t.get('price', 0)):.2f}",
                    "live_value": "无成交",
                    "reason": self._guess_trade_reason(conn, code, direction, target_date),
                    "suggestion": "查看实盘订单状态，确认是否提交/成交",
                    "detail": f"模拟盘有 {len(trades)} 笔成交，实盘无成交记录"
                }
                report.issues.append(issue)
                report.trade_diff_count += 1
            elif 0 < live_qty < sim_qty:
                # 部分成交
                t = trades[0]
                issue = {
                    "issue_type": "trade_mismatch",
                    "severity": "warning",
                    "stock_code": code,
                    "stock_name": t.get('stock_name', ''),
                    "sim_value": f"{direction} {sim_qty}股",
                    "live_value": f"{direction} {live_qty}股（部分成交）",
                    "reason": "partial_fill",
                    "suggestion": "检查剩余订单是否仍在排队，或价格是否需要调整",
                    "detail": f"模拟盘成交 {sim_qty} 股，实盘仅成交 {live_qty} 股"
                }
                report.issues.append(issue)
                report.trade_diff_count += 1
    
    def _guess_trade_reason(self, conn, stock_code: str, direction: str, target_date: str) -> str:
        """根据订单表推断成交缺失的原因"""
        cur = conn.cursor()
        # 查找对应股票的订单
        rows = cur.execute(
            'SELECT * FROM sim_orders WHERE account_id=? AND stock_code=? AND direction=? AND DATE(order_time)=? ORDER BY order_time',
            (self.live_account_id, stock_code, direction, target_date)
        ).fetchall()
        
        if not rows:
            return "not_started"  # 订单都没提交
        
        for r in rows:
            status = r.get('status', '')
            if status in ('REJECTED', 'CANCELLED'):
                return "order_failed"
            if status == 'SUBMITTING':
                return "sync_delay"
            if status == 'PART_TRADED':
                return "partial_fill"
        
        return "risk_blocked"  # 有订单但没成交，可能被风控拦截
    
    def _diagnose_orders(self, report: DiagReport, conn, target_date: str):
        """诊断订单状态异常（被拒绝、超时等）"""
        cur = conn.cursor()
        # 查找 live 账户异常订单
        rows = cur.execute(
            'SELECT * FROM sim_orders WHERE account_id=? AND DATE(order_time)=? AND status IN ("REJECTED", "CANCELLED") ORDER BY order_time',
            (self.live_account_id, target_date)
        ).fetchall()
        
        for r in rows:
            code = r['stock_code']
            reason_map = {
                'REJECTED': 'broker_rejected',
                'CANCELLED': 'timeout',
            }
            issue = {
                "issue_type": "order_abnormal",
                "severity": "warning",
                "stock_code": code,
                "stock_name": r.get('stock_name', ''),
                "sim_value": f"订单状态: {r['status']}",
                "live_value": f"订单状态: {r['status']}",
                "reason": reason_map.get(r['status'], 'order_failed'),
                "suggestion": "查看 QMT 日志确认拒绝原因，检查价格是否合规",
                "detail": f"实盘订单 {r.get('broker_order_id', '')} 状态异常: {r['status']}"
            }
            report.issues.append(issue)
    
    def _generate_conclusion(self, report: DiagReport):
        """生成诊断结论和行动项"""
        report.total_issues = len(report.issues)
        report.critical_count = sum(1 for i in report.issues if i.get('severity') == 'critical')
        report.warning_count = sum(1 for i in report.issues if i.get('severity') == 'warning')
        report.info_count = sum(1 for i in report.issues if i.get('severity') == 'info')
        
        # 统计原因分布
        reason_count = {}
        for i in report.issues:
            r = i.get('reason', 'unknown')
            reason_count[r] = reason_count.get(r,0) + 1
        report.reason_distribution = reason_count
        
        # 生成结论
        if report.total_issues == 0:
            report.conclusion = "✅ 双账户执行一致，未发现显著差异"
            return
        
        # 按原因分类给出结论
        lines = []
        lines.append(f"发现 {report.total_issues} 项差异（{report.critical_count} 项严重，{report.warning_count} 项警告）")
        
        reason_labels = {
            'not_started': '实盘未开启/未运行',
            'risk_blocked': '风控拦截',
            'order_failed': '下单失败',
            'sync_delay': '同步延迟',
            'config_mismatch': '配置差异',
            'broker_rejected': '券商拒绝',
            'timeout': '订单超时',
            'partial_fill': '部分成交',
        }
        
        for reason, count in sorted(reason_count.items(), key=lambda x: -x[1]):
            label = reason_labels.get(reason, reason)
            lines.append(f"  - {label}：{count} 项")
        
        report.conclusion = "\n".join(lines)
        
        # 生成行动项
        action_items = []
        if 'not_started' in reason_count:
            action_items.append("🔴 [紧急] 确认 QMT 已登录且策略已启动，检查实盘自动交易开关")
        if 'risk_blocked' in reason_count:
            action_items.append("🟡 [重要] 检查实盘风控设置（仓位上限、单笔上限、日内预算），确认是否与模拟盘一致")
        if 'order_failed' in reason_count or 'broker_rejected' in reason_count:
            action_items.append("🟡 [重要] 查看 QMT 订单状态和拒绝原因，确认价格是否超出涨跌停限制")
        if 'sync_delay' in reason_count:
            action_items.append("🟢 [提示] 订单可能存在同步延迟，建议等待或手动刷新订单状态")
        if 'config_mismatch' in reason_count:
            action_items.append("🟢 [提示] 检查双账户配置（初始资金、风控参数）是否一致")
        if 'partial_fill' in reason_count:
            action_items.append("🟢 [提示] 部分订单未完全成交，考虑调整价格或分批下单")
        
        report.action_items = action_items
    
    # ========================================
    # 报告输出
    # ========================================
    
    def render_markdown(self, report: DiagReport) -> str:
        """渲染 Markdown 格式报告"""
        lines = []
        lines.append(f"# 🔍 双账户一致性诊断报告")
        lines.append(f"**诊断日期**: {report.trade_date}")
        lines.append(f"**生成时间**: {report.generated_at}")
        lines.append(f"**对比账户**: 模拟盘(id={report.sim_account_id}) vs 实盘(id={report.live_account_id})")
        lines.append("")
        
        # 概览
        lines.append("## 📊 诊断概览")
        lines.append(f"- 总差异数: **{report.total_issues}**")
        lines.append(f"- 严重: **{report.critical_count}** | 警告: **{report.warning_count}** | 提示: **{report.info_count}**")
        lines.append(f"- 持仓差异: {report.position_diff_count} 项")
        lines.append(f"- 成交差异: {report.trade_diff_count} 项")
        lines.append(f"- 现金利用率差异: {report.cash_diff_pct:.1f}%")
        lines.append("")
        
        # 原因分布
        if report.reason_distribution:
            lines.append("## 🎯 原因分布")
            reason_labels = {
                'not_started': '实盘未开启/未运行',
                'risk_blocked': '风控拦截',
                'order_failed': '下单失败',
                'sync_delay': '同步延迟',
                'config_mismatch': '配置差异',
                'broker_rejected': '券商拒绝',
                'timeout': '订单超时',
                'partial_fill': '部分成交',
            }
            for reason, count in sorted(report.reason_distribution.items(), key=lambda x: -x[1]):
                label = reason_labels.get(reason, reason)
                lines.append(f"- {label}: {count} 项")
            lines.append("")
        
        # 详细问题
        if report.issues:
            lines.append("## 🔎 详细问题")
            for i, issue in enumerate(report.issues, 1):
                severity_emoji = {"critical": "🔴", "warning": "🟡", "info": "🟢"}.get(issue.get('severity', 'info'), '⚪')
                lines.append(f"### {severity_emoji} 问题 {i}: {issue.get('issue_type', '')}")
                if issue.get('stock_code'):
                    lines.append(f"**股票**: {issue.get('stock_name', '')} ({issue.get('stock_code', '')})")
                lines.append(f"**模拟盘**: {issue.get('sim_value', '')}")
                lines.append(f"**实盘**: {issue.get('live_value', '')}")
                
                reason_labels_detail = {
                    'not_started': '实盘未开启/未运行',
                    'risk_blocked': '风控拦截',
                    'order_failed': '下单失败',
                    'sync_delay': '同步延迟',
                    'config_mismatch': '配置差异',
                    'broker_rejected': '券商拒绝',
                    'timeout': '订单超时',
                    'partial_fill': '部分成交',
                }
                reason = issue.get('reason', '')
                lines.append(f"**原因**: {reason_labels_detail.get(reason, reason)}")
                lines.append(f"**建议**: {issue.get('suggestion', '')}")
                if issue.get('detail'):
                    lines.append(f"**详情**: {issue.get('detail', '')}")
                lines.append("")
        
        # 结论
        lines.append("## 📝 诊断结论")
        lines.append(report.conclusion)
        lines.append("")
        
        # 行动项
        if report.action_items:
            lines.append("## ✅ 行动建议")
            for item in report.action_items:
                lines.append(f"- {item}")
            lines.append("")
        
        lines.append("_本报告由 REQ-034 双账户诊断模块自动生成_")
        
        return "\n".join(lines)
    
    def save_report(self, report: DiagReport, output_dir: str = None) -> str:
        """保存报告到文件，返回保存路径"""
        if output_dir is None:
            ROOT = Path(__file__).resolve().parents[1]
            output_dir = ROOT / "output" / "diag"
        os.makedirs(output_dir, exist_ok=True)
        
        date_str = report.trade_date.replace("-", "")
        base_name = f"mirror_diag_{date_str}"
        
        # 保存 Markdown
        md_path = os.path.join(output_dir, f"{base_name}.md")
        md_content = self.render_markdown(report)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        
        # 保存 JSON
        json_path = os.path.join(output_dir, f"{base_name}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(asdict(report), f, ensure_ascii=False, indent=2)
        
        logger.info(f"诊断报告已保存: {md_path}")
        return md_path


# ============================================================
# CLI 入口
# ============================================================

def main():
    import argparse
    from datetime import date as Date
    
    parser = argparse.ArgumentParser(description="双账户执行一致性诊断 (REQ-034)")
    parser.add_argument("--date", default=Date.today().isoformat(), help="诊断日期 YYYY-MM-DD")
    parser.add_argument("--db", default=None, help="数据库路径")
    parser.add_argument("--sim-id", type=int, default=1, help="模拟盘账户 ID")
    parser.add_argument("--live-id", type=int, default=2, help="实盘账户 ID")
    parser.add_argument("--output", default=None, help="输出目录")
    parser.add_argument("--print", action="store_true", help="直接打印报告")
    args = parser.parse_args()
    
    diag = MirrorDiagnostics(db_path=args.db, sim_account_id=args.sim_id, live_account_id=args.live_id)
    report = diag.diagnose(target_date=args.date)
    md = diag.render_markdown(report)
    
    if args.print:
        print(md)
    else:
        path = diag.save_report(report, output_dir=args.output)
        print(f"✅ 诊断报告已生成: {path}")
        print(f"\n{md}")


if __name__ == "__main__":
    main()
