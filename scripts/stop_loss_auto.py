#!/usr/bin/env python3
"""
stop_loss_auto.py — 自动止损脚本（REQ-046）

每日扫描 sim_positions 所有持仓：
1. 获取最新实时行情价格
2. 对比 trailing_stop_price（跟踪止损价）
3. 如果现价 <= 止损价则触发卖出
4. 写入 sim_trades、sim_orders、sim_fills
5. 更新 sim_positions 仓位
6. 输出执行结果

运行方式：
  python scripts/stop_loss_auto.py              # 默认数据库
  python scripts/stop_loss_auto.py --dry-run    # 只检查不执行
  python scripts/stop_loss_auto.py --db-path /path/to/db

可被 cron 定时调用（建议每 5-10 分钟一次，盘中）。
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "sim_live_mirror.db"
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 日志 ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────
COMMISSION_RATE = 0.0003
MIN_COMMISSION = 5.0
STAMP_TAX_RATE = 0.001
FIXED_STOP_LOSS_PCT = -0.08  # 固定止损 -8%


# ══════════════════════════════════════════════════════════
# DB 工具
# ══════════════════════════════════════════════════════════

def get_conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def calc_trailing_stop_price(
    entry_price: float,
    highest_price: float,
    current_trailing: float | None = None,
) -> tuple[float, str]:
    """按 REQ-041 计算跟踪止损价；结果只能上移不能下移。"""
    current = float(current_trailing or 0.0)
    if entry_price <= 0 or highest_price <= 0:
        return current, ""

    profit_pct = (highest_price - entry_price) / entry_price
    if profit_pct > 0.20:
        candidate = max(entry_price * 1.10, highest_price * 0.92)
        reason = "浮盈>20%，跟踪止损=max(entry*1.10, high*0.92)"
    elif profit_pct > 0.10:
        candidate = entry_price * 1.02
        reason = "浮盈>10%，止损抬到 entry*1.02"
    elif profit_pct > 0.05:
        candidate = entry_price * 1.00
        reason = "浮盈>5%，止损抬到保本位"
    else:
        candidate = current
        reason = "浮盈未超过5%，跟踪止损未启动"

    candidate = round(float(candidate or 0.0), 4)
    if current > candidate:
        return current, "保持原跟踪止损，不下移"
    return candidate, reason


def calc_fixed_stop_price(entry_price: float) -> float:
    """计算固定止损价（基于成本价 -8%）。"""
    return round(entry_price * (1 + FIXED_STOP_LOSS_PCT), 4)


# ══════════════════════════════════════════════════════════
# 行情获取
# ══════════════════════════════════════════════════════════

def get_latest_prices(codes: list[str]) -> dict[str, dict]:
    """获取新浪实时行情，返回 {code: {name, price, ...}}"""
    if not codes:
        return {}

    import re
    import requests

    def _sina_code(code: str) -> str:
        if code.startswith(("6", "9")):
            return f"sh{code}"
        return f"sz{code}"

    sina_codes = [_sina_code(c) for c in codes]
    url = f"https://hq.sinajs.cn/list={','.join(sina_codes)}"
    headers = {
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = "gbk"
        text = resp.text.strip()
    except Exception as e:
        log.warning("新浪行情请求失败: %s", e)
        return {}

    result = {}
    pattern = re.compile(r'var hq_str_(\w+)="(.*)";')
    for line in text.split("\n"):
        m = pattern.search(line.strip())
        if not m:
            continue
        sina_sym = m.group(1)
        raw = m.group(2)
        if not raw:
            continue
        parts = raw.split(",")
        if len(parts) < 32:
            continue
        code = sina_sym[2:]
        try:
            current_price = float(parts[3]) if parts[3] else 0
            yclose = float(parts[2]) if parts[2] else 0
            if current_price == 0 and yclose > 0:
                current_price = yclose
            result[code] = {
                "name": parts[0],
                "open": float(parts[1]) if parts[1] else 0,
                "high": float(parts[4]) if parts[4] else 0,
                "low": float(parts[5]) if parts[5] else 0,
                "price": current_price,
                "yesterday_close": yclose,
                "volume": float(parts[8]) if parts[8] else 0,
                "amount": float(parts[9]) if parts[9] else 0,
                "date": parts[30],
                "time": parts[31],
            }
        except (ValueError, IndexError):
            pass
    return result


# ══════════════════════════════════════════════════════════
# 核心逻辑
# ══════════════════════════════════════════════════════════

def _do_sell(
    db_path: Path,
    account_id: int,
    stock_code: str,
    stock_name: str,
    quantity: int,
    price: float,
    signal_reason: str,
    pos_id: int,
    dry_run: bool = False,
) -> dict:
    """执行卖出操作。dry_run=True 时只检查不写入。"""
    if dry_run:
        return {
            "success": True,
            "msg": f"[DRY-RUN] 卖出 {stock_code} {quantity}股 @ {price:.4f}",
            "amount": round(price * quantity, 2),
            "dry_run": True,
        }

    conn = get_conn(db_path)
    try:
        cur = conn.cursor()

        # 1. 幂等检查：今日是否已卖出该股票
        trade_date = str(date.today())
        cur.execute(
            "SELECT 1 FROM sim_trades "
            "WHERE account_id = ? AND stock_code = ? AND trade_date = ? "
            "AND direction = 'SELL' AND signal_reason LIKE 'stop_loss_auto%' "
            "LIMIT 1",
            (account_id, stock_code, trade_date),
        )
        if cur.fetchone():
            return {
                "success": False,
                "msg": f"今日已止损卖出 {stock_code}，跳过（幂等保护）",
                "idempotent_skip": True,
            }

        # 2. 获取账户
        cur.execute("SELECT cash FROM sim_account WHERE id = ?", (account_id,))
        acct_row = cur.fetchone()
        if not acct_row:
            return {"success": False, "msg": f"账户 {account_id} 不存在"}

        # 3. 检查持仓是否还在
        cur.execute(
            "SELECT id, quantity FROM sim_positions WHERE id = ? AND quantity > 0",
            (pos_id,),
        )
        pos_check = cur.fetchone()
        if not pos_check:
            return {
                "success": False,
                "msg": f"持仓 {pos_id} 已清仓或不存在",
                "idempotent_skip": True,
            }

        amount = price * quantity
        commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
        tax = amount * STAMP_TAX_RATE
        net_income = amount - commission - tax

        # 4. 增加现金
        new_cash = float(acct_row["cash"]) + net_income
        cur.execute(
            "UPDATE sim_account SET cash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (round(new_cash, 2), account_id),
        )

        # 5. 删除持仓（清仓）— TASK-20260718-2003-001: DELETE 替代 UPDATE SET quantity=0
        cur.execute(
            "DELETE FROM sim_positions WHERE id = ?",
            (pos_id,),
        )

        # 6. 写交易记录
        cur.execute(
            "INSERT INTO sim_trades "
            "(account_id, trade_date, stock_code, stock_name, direction, "
            "price, quantity, amount, commission, tax, signal_reason, broker) "
            "VALUES (?, ?, ?, ?, 'SELL', ?, ?, ?, ?, ?, ?, ?)",
            (
                account_id, trade_date, stock_code, stock_name,
                round(price, 4), quantity, round(amount, 2),
                round(commission, 2), round(tax, 2),
                signal_reason, "sim_stop_loss_auto",
            ),
        )

        # 7. 写订单记录
        order_id = f"SLA-{stock_code}-{int(time.time() * 1000)}"
        cur.execute(
            "INSERT INTO sim_orders "
            "(account_id, order_id, stock_code, stock_name, direction, offset, "
            "price, quantity, traded, status, order_time, broker, signal_reason) "
            "VALUES (?, ?, ?, ?, 'SELL', 'CLOSE', ?, ?, ?, 'ALL_TRADED', "
            "datetime('now', 'localtime'), 'sim_stop_loss_auto', ?)",
            (
                account_id, order_id, stock_code, stock_name,
                round(price, 4), quantity, quantity,
                signal_reason,
            ),
        )

        # 8. 写成交记录
        cur.execute(
            "INSERT INTO sim_fills "
            "(account_id, order_id, stock_code, stock_name, direction, "
            "trade_price, trade_volume, trade_amount, commission, tax, "
            "trade_time, broker, strategy_name) "
            "VALUES (?, ?, ?, ?, 'SELL', ?, ?, ?, ?, ?, "
            "datetime('now', 'localtime'), 'sim_stop_loss_auto', 'stop_loss_auto')",
            (
                account_id, order_id, stock_code, stock_name,
                round(price, 4), quantity, round(amount, 2),
                round(commission, 2), round(tax, 2),
            ),
        )

        # 9. 更新 threshold_state（如果有对应记录）
        cur.execute(
            "UPDATE threshold_state SET status = 'executed', notes = "
            "CASE WHEN notes IS NULL OR notes = '' THEN ? "
            "ELSE notes || ' | ' || ? END, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE stock_code = ? AND status IN ('armed', 'pending') "
            "AND rule_name IN ('trend_break', 'take_profit', 'stop_loss', 'trailing_stop')",
            (
                f"止损自动执行: {quantity}股 @ {price:.4f}",
                f"止损自动执行: {quantity}股 @ {price:.4f}",
                stock_code,
            ),
        )

        conn.commit()
        return {
            "success": True,
            "msg": f"卖出 {stock_code} {quantity}股 @ {price:.4f}",
            "amount": round(amount, 2),
            "commission": round(commission, 2),
            "tax": round(tax, 2),
            "order_id": order_id,
        }
    finally:
        conn.close()


def scan_and_execute(db_path: Path, dry_run: bool = False) -> dict:
    """扫描所有持仓，检查止损条件，执行卖出。"""
    conn = get_conn(db_path)
    try:
        cur = conn.cursor()

        # 获取所有持仓
        cur.execute(
            "SELECT id, account_id, stock_code, stock_name, quantity, avg_cost, "
            "current_price, trailing_stop_price, highest_price "
            "FROM sim_positions WHERE quantity > 0"
        )
        positions = [dict(r) for r in cur.fetchall()]

        if not positions:
            log.info("当前无持仓，无需扫描")
            return {
                "scanned": 0,
                "triggered": 0,
                "safe": 0,
                "errors": 0,
                "details": {"triggered": [], "safe": [], "errors": []},
            }

        # 获取实时价格
        codes = list(set(r["stock_code"] for r in positions))
        prices = get_latest_prices(codes)
        log.info("获取到 %d/%d 只股票实时行情", len(prices), len(codes))

        triggered = []
        safe = []
        errors_list = []

        for pos in positions:
            code = pos["stock_code"]
            name = pos["stock_name"]
            pos_id = pos["id"]
            account_id = pos["account_id"]
            qty = pos["quantity"]
            avg_cost = float(pos["avg_cost"] or 0)
            sim_price = float(pos["current_price"] or 0)
            trailing_stop = float(pos["trailing_stop_price"] or 0)
            highest_price = float(pos["highest_price"] or avg_cost or 0)

            # 获取实时价格
            price_data = prices.get(code, {})
            current_price = float(price_data.get("price", 0) or 0)

            if current_price <= 0:
                # 非交易时段，用模拟价格
                current_price = sim_price
                if current_price <= 0:
                    errors_list.append({
                        "stock_code": code,
                        "stock_name": name,
                        "reason": "无法获取价格（新浪无数据，模拟价格也为0）",
                    })
                    continue

            # 计算实际浮亏
            loss_pct = (current_price - avg_cost) / avg_cost if avg_cost > 0 else 0

            # 决定止损价（优先级：跟踪止损 > 固定止损）
            stop_price = trailing_stop if trailing_stop > 0 else calc_fixed_stop_price(avg_cost)

            # 检查是否触发
            if current_price <= stop_price:
                result = _do_sell(
                    db_path=db_path,
                    account_id=account_id,
                    stock_code=code,
                    stock_name=name,
                    quantity=qty,
                    price=current_price,
                    signal_reason=(
                        f"stop_loss_auto|止损价{stop_price:.3f}|"
                        f"现价{current_price:.3f}|浮亏{loss_pct*100:.2f}%"
                    ),
                    pos_id=pos_id,
                    dry_run=dry_run,
                )
                if result.get("success"):
                    triggered.append({
                        "stock_code": code,
                        "stock_name": name,
                        "account_id": account_id,
                        "quantity": qty,
                        "avg_cost": avg_cost,
                        "sell_price": current_price,
                        "stop_price": stop_price,
                        "loss_pct": loss_pct,
                        "result": result,
                    })
                    tag = "[DRY-RUN] " if dry_run else ""
                    log.info(
                        "  %s✅ 触发 [%s] %s: %d股 @ %.4f (止损价 %.4f, 浮亏 %.2f%%)",
                        tag, code, name, qty, current_price, stop_price, loss_pct * 100,
                    )
                else:
                    if result.get("idempotent_skip"):
                        log.info("  - 幂等跳过 [%s] %s: 今日已卖出", code, name)
                    else:
                        errors_list.append({
                            "stock_code": code,
                            "stock_name": name,
                            "reason": result["msg"],
                        })
                        log.warning("  ✗ 卖出失败 [%s] %s: %s", code, name, result["msg"])
            else:
                safe.append({
                    "stock_code": code,
                    "stock_name": name,
                    "current_price": current_price,
                    "stop_price": stop_price,
                    "loss_pct": loss_pct,
                })

        return {
            "scanned": len(positions),
            "triggered": len(triggered),
            "safe": len(safe),
            "errors": len(errors_list),
            "dry_run": dry_run,
            "details": {
                "triggered": triggered,
                "safe": safe,
                "errors": errors_list,
            },
        }
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="自动止损脚本 - 扫描持仓并执行止损卖出")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="数据库路径")
    parser.add_argument("--dry-run", action="store_true", help="只检查不执行")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        log.error("数据库不存在: %s", db_path)
        sys.exit(1)

    mode = "[DRY-RUN]" if args.dry_run else "[LIVE]"
    log.info("=" * 60)
    log.info("自动止损扫描 %s", mode)
    log.info("数据库: %s", db_path)
    log.info("时间: %s", datetime.now().isoformat())
    log.info("=" * 60)

    result = scan_and_execute(db_path, dry_run=args.dry_run)

    log.info("")
    log.info("=" * 60)
    log.info("扫描结果")
    log.info("=" * 60)
    log.info("  扫描持仓: %d", result["scanned"])
    log.info("  触发卖出: %d", result["triggered"])
    log.info("  安全持有: %d", result["safe"])
    log.info("  错误: %d", result["errors"])
    if result["triggered"] > 0:
        log.info("")
        log.info("触发详情:")
        for t in result["details"]["triggered"]:
            log.info(
                "  [%s] %s: %d股 @ %.4f (止损价 %.4f, 浮亏 %.2f%%)",
                t["stock_code"], t["stock_name"],
                t["quantity"], t["sell_price"],
                t["stop_price"], t["loss_pct"] * 100,
            )
    if result["safe"] > 0:
        log.info("")
        log.info("安全持仓:")
        for s in result["details"]["safe"]:
            log.info(
                "  [%s] %s: 现价 %.4f > 止损价 %.4f (浮亏 %.2f%%)",
                s["stock_code"], s["stock_name"],
                s["current_price"], s["stop_price"],
                s["loss_pct"] * 100,
            )

    # 保存结果
    report = {
        "timestamp": datetime.now().isoformat(),
        "mode": "dry_run" if args.dry_run else "live",
        "db_path": str(db_path),
        **result,
    }
    report_path = OUTPUT_DIR / f"stop_loss_auto_{date.today().isoformat()}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    log.info("")
    log.info("报告已保存: %s", report_path)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
