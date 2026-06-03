#!/usr/bin/env python3
"""
stop_profit_monitor.py — 止盈监控

每分钟检查持仓中浮盈超过止盈线的股票，自动分批卖出锁定利润。
每次触发时卖出 1/3 仓位，剩余仓位继续跑。

设计为被 Windows 任务计划程序调用（每 1-5 分钟）。

参考：config.yaml 中 risk.take_profit_pct（默认 0.15，即 +15%）
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QUANT_DB_PATH', str(ROOT / 'data' / 'sim_live_mirror.db'))

from sim.db import get_conn
from broker.sim_broker import SimBroker


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('stop_profit')


def load_take_profit_pct() -> float:
    """从 config.yaml 读取止盈线，默认 0.15"""
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
        return float((cfg.get('risk') or {}).get('take_profit_pct', 0.15))
    except Exception:
        return 0.15


def check_and_sell(account_id: int = 1, sell_fraction: float = 1.0/3.0) -> int:
    """
    扫描 account_id 的持仓，对触发止盈的股票分批卖出。
    返回实际卖出次数。
    """
    take_profit_pct = load_take_profit_pct()
    broker = SimBroker(account_id=account_id)
    broker.connect()

    conn = get_conn()
    try:
        cur = conn.execute(
            "SELECT stock_code, stock_name, quantity, avg_cost, current_price, pnl_pct "
            "FROM sim_positions "
            "WHERE account_id = ? AND quantity > 0 "
            "ORDER BY pnl_pct DESC",
            (account_id,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    sold_count = 0
    for row in rows:
        code, name, qty, avg_cost, cur_price, pnl_pct = row
        if pnl_pct is None:
            continue
        if pnl_pct >= take_profit_pct * 100:  # pnl_pct 是百分比
            sell_qty = max(1, int(qty * sell_fraction))
            logger.info(
                f"🎯 触发止盈 [{code}] {name}："
                f"成本 ¥{avg_cost:.2f}，现价 ¥{cur_price:.2f}，"
                f"浮盈 {pnl_pct:.2f}% >= 止盈线 {take_profit_pct*100:.1f}%，"
                f"卖出 {sell_qty}/{qty} 股锁定利润"
            )
            try:
                result = broker.sell(
                    stock_code=code,
                    price=cur_price,
                    quantity=sell_qty,
                    stock_name=name,
                    signal_reason=f"自动止盈分批卖出（浮盈 {pnl_pct:.1f}%）",
                )
                if result.get('success'):
                    logger.info(f"✅ [{code}] 止盈卖出成功：{sell_qty}股")
                    sold_count += 1
                else:
                    logger.error(f"❌ [{code}] 止盈卖出失败：{result.get('msg')}")
            except Exception as e:
                logger.error(f"❌ [{code}] 止盈卖出异常：{e}")

    if sold_count == 0:
        logger.info("✅ 无触发止盈的持仓")
    else:
        logger.info(f"✅ 本次共止盈卖出 {sold_count} 只")
    return sold_count


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='止盈监控')
    parser.add_argument('--account-id', type=int, default=1, help='账户 ID（默认 1=学习账户）')
    parser.add_argument('--fraction', type=float, default=1.0/3.0, help='每次卖出仓位比例（默认 1/3）')
    parser.add_argument('--dry-run', action='store_true', help='仅检查，不实际卖出')
    args = parser.parse_args()

    if args.dry_run:
        take_profit_pct = load_take_profit_pct()
        conn = get_conn()
        try:
            cur = conn.execute(
                "SELECT stock_code, stock_name, quantity, avg_cost, current_price, pnl_pct "
                "FROM sim_positions WHERE account_id = ? AND quantity > 0",
                (args.account_id,),
            )
            for row in cur.fetchall():
                code, name, qty, cost, price, pct = row
                flag = "🎯 触发止盈" if pct is not None and pct >= take_profit_pct * 100 else "✅ 正常"
                print(f"{flag} [{code}] {name} 浮盈 {pct:.2f}%" if pct is not None else f"⚠️ [{code}] {name} pnl_pct=None")
        finally:
            conn.close()
    else:
        check_and_sell(args.account_id, args.fraction)
