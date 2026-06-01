"""scripts/daily_review_vnpy.py — vnpy 双账户复盘脚本（Phase 2 完成版）

数据源：
  - sim 25000：sim/db.py 直读 sim.db
  - QMT mini 1000 万 (90072426)：尝试用 broker.factory.get_broker('qmt', dry_run=True)
    连 QMT mini，拉 query_account / query_positions；
    QMT 没启动或 connect 失败时降级用 sim_live_mirror.db（最近一次镜像）

输出：
  - docs/reviews/YYYY-MM-DD.md
  - 通过 notifier.push_text 推到企微（dry-run 默认开，环境变量 NOTIFIER_DRY_RUN=0 可真发）

用法：
  python -m scripts.daily_review_vnpy [--day YYYY-MM-DD] [--no-qmt] [--push]
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import yaml
from datetime import date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from notifier import push_text
from sim.db import get_conn  # noqa: E402
from sim.precision import fmt_cost  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("daily_review_vnpy")


# ============================================================
# 安全闸门
# ============================================================
FORBIDDEN_ACCOUNTS = {"8890461376"}


def _assert_safe(account_id: Optional[str]):
    if account_id and str(account_id) in FORBIDDEN_ACCOUNTS:
        raise RuntimeError(f"⚠️ 禁止访问真实账户 {account_id}")


# ============================================================
# sim 25000 数据
# ============================================================
def fetch_unmatched_sell_confirmations(day: str, db_path: Path) -> list[dict]:
    """Return executed sell confirmations that have no matching sim_trades row.

    BUG-017: threshold_state could be marked ``executed`` while the broker/sim
    trade insert failed or was not persisted. Surface these audit rows in the
    daily review so SELL execution is not hidden by an empty trade table.
    """
    import sqlite3
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        has_state = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='threshold_state'"
        ).fetchone()
        if not has_state:
            conn.close()
            return []
        rows = cur.execute(
            """
            SELECT ts.*
            FROM threshold_state ts
            WHERE ts.status='executed'
              AND ts.next_day_confirmed_at=?
              AND ts.rule_name IN ('trend_break', 'take_profit', 'stop_loss', 'trailing_stop')
              AND NOT EXISTS (
                  SELECT 1 FROM sim_trades tr
                  WHERE tr.account_id=1
                    AND tr.stock_code=ts.stock_code
                    AND tr.trade_date=ts.next_day_confirmed_at
                    AND tr.direction='SELL'
              )
            ORDER BY ts.updated_at, ts.id
            """,
            (day,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning("读取卖出执行审计失败 %s: %s", db_path, e)
        return []


def fetch_sim_snapshot(day: str, db_path: Path) -> dict:
    """从指定 sim*.db 拉账户/持仓/当日成交 (直接开 sqlite，不走 sim/db.py 的全局常量)"""
    import sqlite3
    snap = {"account": None, "positions": [], "trades": [], "unmatched_sell_confirmations": [], "db_path": str(db_path)}
    if not db_path.exists():
        logger.warning("DB 不存在: %s", db_path)
        return snap
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT id, account_name, initial_cash, cash, total_value FROM sim_account WHERE id=1")
        row = cur.fetchone()
        if row:
            snap["account"] = {
                "id": row["id"], "name": row["account_name"],
                "initial_cash": row["initial_cash"],
                "cash": row["cash"], "total_value": row["total_value"],
                "return_pct": (row["total_value"] / row["initial_cash"] - 1) * 100
                              if row["initial_cash"] else 0.0,
            }
        cur.execute("SELECT stock_code, stock_name, quantity, avg_cost, current_price, "
                    "market_value, pnl, pnl_pct FROM sim_positions WHERE quantity>0")
        snap["positions"] = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT trade_date, stock_code, stock_name, direction, price, quantity, "
            "amount, signal_reason, broker FROM sim_trades WHERE trade_date=? "
            "ORDER BY created_at",
            (day,),
        )
        snap["trades"] = [dict(r) for r in cur.fetchall()]
        conn.close()
        snap["unmatched_sell_confirmations"] = fetch_unmatched_sell_confirmations(day, db_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("读取 %s 失败: %s", db_path, e)
    return snap


# ============================================================
# QMT mini 数据（尝试连真 broker，失败降级 sim_live_mirror）
# ============================================================
def fetch_qmt_snapshot(day: str, allow_qmt: bool = True) -> dict:
    """优先连 QMT mini → 失败回退 sim_live_mirror.db"""
    snap: dict = {"source": "none", "account": None, "positions": [], "trades": []}

    if allow_qmt:
        try:
            cfg = yaml.safe_load((ROOT / "config.local.yaml").read_text(encoding="utf-8")) or {}
            live_cfg = (cfg.get("broker") or {}).get("live") or {}
            qmt_account = str(live_cfg.get("qmt_account", ""))
            _assert_safe(qmt_account)
            qmt_path = live_cfg.get("qmt_path")
            xtq = live_cfg.get("xtquant_site_packages")
            if not qmt_account or not qmt_path:
                raise RuntimeError("config.local.yaml 缺少 broker.live 配置")

            from broker.factory import get_broker
            logger.info("尝试连 QMT mini account=%s dry_run=True", qmt_account)
            broker = get_broker(
                "qmt",
                qmt_path=qmt_path,
                qmt_account=qmt_account,
                session_id=int(live_cfg.get("session_id", 970515)),
                dry_run=True,
                xtquant_site_packages=xtq,
            )
            try:
                acc = broker.get_account()
                pos = broker.get_positions()
                snap["source"] = "qmt_live"
                snap["account"] = {
                    "id": qmt_account, "name": "QMT-mini",
                    "initial_cash": acc.initial_cash, "cash": acc.cash,
                    "total_value": acc.total_value,
                    "market_value": acc.market_value,
                }
                snap["positions"] = [
                    {"stock_code": p.stock_code, "stock_name": p.stock_name,
                     "quantity": p.quantity, "avg_cost": p.avg_cost,
                     "current_price": p.current_price, "market_value": p.market_value,
                     "pnl": p.pnl, "pnl_pct": p.pnl_pct}
                    for p in pos if p.quantity > 0
                ]
                # QMT 不直接给"今日成交"，先空。后续用 vnpy MainEngine.get_all_trades() 补
                logger.info("✅ QMT 连接成功，positions=%d cash=%.2f",
                            len(snap["positions"]), acc.cash)
                return snap
            finally:
                try:
                    broker.disconnect()
                except Exception:
                    pass
        except Exception as e:  # noqa: BLE001
            logger.warning("QMT 直连失败，降级用 sim_live_mirror.db: %s", e)

    # 降级：QMT 连不上 → 只说明，不拿 sim_live_mirror 充数（避免两边重复）
    snap["source"] = "unavailable"
    snap["note"] = "QMT 未连接且 sim_live_mirror.db 已被 sim 25000 占用；QMT 侧需接 vnpy MainEngine 补数据。"
    return snap


# ============================================================
# 资金口径变更检测
# ============================================================
def _parse_money(value: str) -> Optional[float]:
    """从 Markdown 表格单元格中解析金额，忽略逗号、空格和告警符号。"""
    if not value:
        return None
    m = re.search(r"-?[0-9][0-9,]*(?:\.[0-9]+)?", value)
    if not m:
        return None
    return float(m.group(0).replace(",", ""))


def _extract_report_initial_cash(report_path: Path, account_label: str) -> Optional[float]:
    """从历史复盘 Markdown 的账户概览表中提取指定账户初始资金。"""
    try:
        for line in report_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 4 and cells[0] == account_label:
                return _parse_money(cells[2])
    except OSError as e:
        logger.warning("读取历史复盘失败 %s: %s", report_path, e)
    return None


def _previous_initial_cash_mismatch(day: str, account_label: str, current: float,
                                    reports_dir: Path | None = None) -> Optional[dict]:
    """查找目标日期之前最近一份与当前 initial_cash 不同的报告。"""
    reports_dir = reports_dir or (ROOT / "docs" / "reviews")
    if not reports_dir.exists():
        return None

    candidates = []
    for p in reports_dir.glob("*.md"):
        stem = p.stem
        if stem >= day:
            continue
        cash = _extract_report_initial_cash(p, account_label)
        if cash is not None and abs(float(cash) - current) > 0.01:
            candidates.append({"day": stem, "path": p, "initial_cash": cash})
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x["day"])[-1]


def detect_capital_basis_changes(day: str, sim_snap: dict, qmt_snap: dict,
                                 reports_dir: Path | None = None) -> list[dict]:
    """检测同一报告账户在跨日报告中的 initial_cash 是否跳变。"""
    checks = [
        ("sim 25000", sim_snap.get("account")),
        ("QMT mini 90072426", qmt_snap.get("account")),
    ]
    changes = []
    for label, acc in checks:
        if not acc or not acc.get("initial_cash"):
            continue
        current = float(acc.get("initial_cash") or 0)
        prev = _previous_initial_cash_mismatch(day, label, current, reports_dir)
        if not prev:
            continue
        previous = float(prev["initial_cash"])
        changes.append({
            "account": label,
            "current": current,
            "previous": previous,
            "previous_day": prev["day"],
            "previous_path": str(prev["path"]),
        })
    return changes


# ============================================================
# Markdown 报告
# ============================================================
def render_markdown(day: str, sim_snap: dict, qmt_snap: dict,
                    reports_dir: Path | None = None) -> str:
    lines = [f"# 双账户复盘 {day}", ""]
    basis_changes = detect_capital_basis_changes(day, sim_snap, qmt_snap, reports_dir)
    changed_accounts = {c["account"] for c in basis_changes}

    # ---- 概览 ----
    lines.append("## 一、账户概览")
    lines.append("| 账户 | 来源 | 初始资金 | 现金 | 总资产 | 浮动收益率 |")
    lines.append("|------|------|---------:|-----:|-------:|-----------:|")

    def _fmt_acc(name: str, source: str, acc: Optional[dict]) -> str:
        if not acc:
            return f"| {name} | {source} | - | - | - | - |"
        ret = ((acc.get("total_value", 0) / (acc.get("initial_cash") or 1)) - 1) * 100 \
            if acc.get("initial_cash") else 0.0
        initial_text = f"{acc.get('initial_cash', 0):,.0f}"
        ret_text = f"{ret:+.2f}%"
        if name in changed_accounts:
            initial_text += " ⚠️"
            ret_text += "（当前口径）"
        return (f"| {name} | {source} | {initial_text} "
                f"| {acc.get('cash', 0):,.2f} | {acc.get('total_value', 0):,.2f} "
                f"| {ret_text} |")

    lines.append(_fmt_acc("sim 25000", Path(sim_snap.get('db_path', '')).name, sim_snap.get("account")))
    lines.append(_fmt_acc("QMT mini 90072426", qmt_snap.get("source", "?"),
                          qmt_snap.get("account")))
    lines.append("")

    if basis_changes:
        lines.append("### ⚠️ 资金口径变更提示")
        for c in basis_changes:
            lines.append(
                f"- {c['account']} 初始资金从 {c['previous_day']} 的 "
                f"¥{c['previous']:,.0f} 变为当前 ¥{c['current']:,.0f}；"
                "跨日收益率/总资产对比已暂停解释，请仅按当前资金口径阅读本日报告。"
            )
        lines.append("")

    # ---- 持仓对比 ----
    lines.append("## 二、持仓对比")
    sim_codes = {p["stock_code"] for p in sim_snap.get("positions", [])}
    qmt_codes = {p["stock_code"] for p in qmt_snap.get("positions", [])}
    common = sorted(sim_codes & qmt_codes)
    sim_only = sorted(sim_codes - qmt_codes)
    qmt_only = sorted(qmt_codes - sim_codes)
    lines.append(f"- 共同持仓: {', '.join(common) or '无'}")
    lines.append(f"- 仅 sim 持有: {', '.join(sim_only) or '无'}")
    lines.append(f"- 仅 QMT 持有: {', '.join(qmt_only) or '无'}")
    lines.append("")

    # sim 持仓详表
    lines.append("### sim 持仓")
    lines.append("| 代码 | 名称 | 数量 | 成本 | 现价 | 市值 | 浮盈 | 浮盈% |")
    lines.append("|------|------|----:|----:|----:|----:|----:|----:|")
    for p in sim_snap.get("positions", []):
        lines.append(f"| {p['stock_code']} | {p.get('stock_name', '-')} | "
                     f"{p['quantity']} | {fmt_cost(p.get('avg_cost', 0))} | "
                     f"{p.get('current_price', 0):.2f} | {p.get('market_value', 0):,.2f} | "
                     f"{p.get('pnl', 0):,.2f} | {p.get('pnl_pct', 0):+.2f}% |")
    if not sim_snap.get("positions"):
        lines.append("| - | - | - | - | - | - | - | - |")
    lines.append("")

    lines.append("### QMT 持仓")
    lines.append("| 代码 | 名称 | 数量 | 成本 | 现价 | 市值 | 浮盈 |")
    lines.append("|------|------|----:|----:|----:|----:|----:|")
    for p in qmt_snap.get("positions", []):
        lines.append(f"| {p['stock_code']} | {p.get('stock_name', '-')} | "
                     f"{p['quantity']} | {fmt_cost(p.get('avg_cost', 0))} | "
                     f"{p.get('current_price', 0):.2f} | {p.get('market_value', 0):,.2f} | "
                     f"{p.get('pnl', 0):,.2f} |")
    if not qmt_snap.get("positions"):
        lines.append("| - | - | - | - | - | - | - |")
    lines.append("")

    # ---- 当日交易 ----
    lines.append(f"## 三、{day} 当日交易")

    def _md_cell(value, max_len: int | None = None) -> str:
        """Return a safe Markdown table cell.

        Trade signal_reason often contains a literal pipe, e.g.
        "自动: buy_zone | 💰 ...".  If left unescaped, the generated row has
        one more column than the header and the broker cell is shifted.  Keep
        newlines compact and escape pipes so every trade row remains 8 cells.
        """
        text = "" if value is None else str(value)
        text = " ".join(text.splitlines()).strip()
        if max_len is not None and len(text) > max_len:
            text = text[:max_len]
        return text.replace("|", r"\|")

    def _money(value, default=0.0) -> float:
        try:
            return float(value if value is not None else default)
        except (TypeError, ValueError):
            return float(default)

    def _trade_block(title: str, trades: list):
        lines.append(f"### {title} ({len(trades)} 笔)")
        if not trades:
            lines.append("（无）")
            return
        lines.append("| 时间/标记 | 股票 | 方向 | 数量 | 价格 | 金额 | 信号 | broker |")
        lines.append("|---------|------|----|----:|----:|-----:|------|--------|")
        for t in trades:
            stock = f"{t.get('stock_code', '')} {t.get('stock_name', '')}".strip()
            signal = _md_cell(t.get('signal_reason') or '', 48)
            broker_name = _md_cell(t.get('broker') or '-', 32)
            lines.append(f"| {_md_cell(t.get('trade_date', ''))} | "
                         f"{_md_cell(stock)} | "
                         f"{_md_cell(t.get('direction', ''))} | {t.get('quantity', 0)} | "
                         f"{_money(t.get('price')):.2f} | {_money(t.get('amount')):,.2f} | "
                         f"{signal} | {broker_name} |")

    _trade_block("sim 25000 成交", sim_snap.get("trades", []))
    _trade_block(f"QMT mini ({qmt_snap.get('source','?')}) 成交", qmt_snap.get("trades", []))

    # BUG-017: threshold_state 已确认/执行卖出，但 sim_trades 没有 SELL 记录时，
    # 不能让复盘静默显示“无卖出”。这里单独列出待回填/对账项。
    missing_sells = sim_snap.get("unmatched_sell_confirmations", [])
    if missing_sells:
        lines.append("### ⚠️ 卖出执行确认但成交表缺失")
        lines.append("| 确认日 | 股票 | 规则 | 阈值 | 确认价 | 状态 | 备注 |")
        lines.append("|------|------|------|----:|-----:|------|------|")
        for r in missing_sells:
            stock = f"{r.get('stock_code', '')} {r.get('stock_name', '')}".strip()
            lines.append(
                f"| {_md_cell(r.get('next_day_confirmed_at', day))} | "
                f"{_md_cell(stock)} | {_md_cell(r.get('rule_name', ''))} | "
                f"{_money(r.get('rule_threshold')):.2f} | {_money(r.get('next_day_price')):.2f} | "
                f"{_md_cell(r.get('status', ''))} | {_md_cell(r.get('notes', ''), 60)} |"
            )
        lines.append("> 这些记录来自 threshold_state；需核对 broker 日志并补写 sim_trades，避免实现盈亏/复盘漏计。")
    lines.append("")

    # ---- 订单/成交回放（REQ-011 OmsEngine 持久化）----
    import sys
    sys.path.insert(0, str(ROOT))
    try:
        from sim.db import replay_timeline as _replay_fn
        replay_text = _replay_fn(account_id=1, day=day)
        lines.append("## 五、订单/成交回放（OmsEngine）")
        lines.append("")
        lines.append(replay_text)
        lines.append("")
    except Exception as e:  # noqa: BLE001
        logger.warning("OmsEngine 回放失败（可能无数据）: %s", e)

    # ---- 摘要 / 提示 ----
    lines.append("## 六、备注")
    lines.append(f"- QMT 数据来源：`{qmt_snap.get('source','?')}` "
                 f"(live = 实时 broker，live_mirror = sim_live_mirror.db 最近镜像)")
    lines.append("- 订单/成交回放由 vnpy OmsEngine EVENT_ORDER/EVENT_TRADE 持久化驱动（REQ-011）。")
    lines.append(f"- 报告生成时间: {date.today().isoformat()}")
    return "\n".join(lines) + "\n"


def short_summary_for_push(day: str, sim_snap: dict, qmt_snap: dict) -> str:
    sim_acc = sim_snap.get("account") or {}
    qmt_acc = qmt_snap.get("account") or {}
    sim_pos_n = len(sim_snap.get("positions", []))
    qmt_pos_n = len(qmt_snap.get("positions", []))
    return (f"📊 [{day}] 双账户复盘\n"
            f"sim 25k 总资产 {sim_acc.get('total_value', 0):,.2f} ({sim_pos_n} 仓)\n"
            f"QMT mini 总资产 {qmt_acc.get('total_value', 0):,.2f} ({qmt_pos_n} 仓) "
            f"src={qmt_snap.get('source','?')}\n"
            f"sim 当日 {len(sim_snap.get('trades', []))} 笔 / QMT {len(qmt_snap.get('trades', []))} 笔")


# ============================================================
# CLI
# ============================================================
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--day", default=date.today().isoformat())
    p.add_argument("--no-qmt", action="store_true",
                   help="跳过尝试连 QMT，直接读 sim_live_mirror.db")
    p.add_argument("--push", action="store_true",
                   help="实际推送企微（默认走 dry-run）")
    p.add_argument("--out-dir", default=str(ROOT / "docs" / "reviews"))
    p.add_argument("--sim-db", default=None,
                   help="sim 账户 DB 路径，默认 data/sim_live_mirror.db")
    return p.parse_args()


def main():
    args = parse_args()
    day = args.day
    if args.push:
        os.environ["NOTIFIER_DRY_RUN"] = "0"
    else:
        os.environ.setdefault("NOTIFIER_DRY_RUN", "1")

    print(f"==== vnpy 双账户复盘 {day} ====")

    # sim 25000 = sim_live_mirror.db（用户实际账本）
    # 如果你想读 sim.db（旧空账户），加 --sim-db data/sim.db
    sim_db_path = Path(args.sim_db) if args.sim_db else ROOT / "data" / "sim_live_mirror.db"
    if not sim_db_path.exists():
        sim_db_path = ROOT / "data" / "sim.db"
    sim_snap = fetch_sim_snapshot(day, sim_db_path)
    qmt_snap = fetch_qmt_snapshot(day, allow_qmt=not args.no_qmt)

    md = render_markdown(day, sim_snap, qmt_snap)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{day}.md"
    out_file.write_text(md, encoding="utf-8")
    print(f"✅ 复盘报告已写入 {out_file}")

    summary = short_summary_for_push(day, sim_snap, qmt_snap)
    push_text(summary)
    print(summary)


if __name__ == "__main__":
    main()
