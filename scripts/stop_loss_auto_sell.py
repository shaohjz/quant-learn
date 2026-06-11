#!/usr/bin/env python3
"""
stop_loss_auto_sell.py — 止损自动卖出监控

每分钟检查持仓中触发止损条件的股票，自动调用 broker.sell() 完成止损。
设计为被 Windows 任务计划程序调用（每 1-5 分钟）。

参考：config.yaml 中 risk.stop_loss_pct（默认 -0.08，即 -8%）
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
logger = logging.getLogger('stop_loss')


def load_stop_loss_pct() -> float:
    """从 config.yaml 读取止损线，默认 -0.08"""
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
        return float((cfg.get('risk') or {}).get('stop_loss_pct', -0.08))
    except Exception:
        return -0.08


def check_and_sell(account_id: int = 1) -> int:
    """
    扫描 account_id 的持仓，对触发止损的股票自动卖出。
    返回实际卖出次数。
    """
    stop_loss_pct = load_stop_loss_pct()
    broker = SimBroker(account_id=account_id)
    broker.connect()

    conn = get_conn()
    try:
        cur = conn.execute(
            "SELECT stock_code, stock_name, quantity, avg_cost, current_price, pnl_pct "
            "FROM sim_positions "
            "WHERE account_id = ? AND quantity > 0 "
            "ORDER BY pnl_pct ASC",
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
        if pnl_pct <= stop_loss_pct * 100:  # pnl_pct 是百分比
            logger.warning(
                f"🚨 触发止损 [{code}] {name}："
                f"成本 ¥{avg_cost:.2f}，现价 ¥{cur_price:.2f}，"
                f"浮亏 {pnl_pct:.2f}% <= 止损线 {stop_loss_pct*100:.1f}%"
            )
            try:
                from sim.sell_signal_audit import build_sell_signal_reason
                _sr = build_sell_signal_reason(
                    'stop_loss', trigger_price=cur_price, volume=qty,
                    extra=f'浮亏{pnl_pct:.1f}%',
                )
            except Exception:
                _sr = f'stop_loss|触发价{cur_price:.3f}|量能{qty}|浮亏{pnl_pct:.1f}%'
            try:
                result = broker.sell(
                    stock_code=code,
                    price=cur_price,
                    quantity=qty,
                    stock_name=name,
                    signal_reason=_sr,
                    signal_detail={
                        "signal": "SELL",
                        "trigger_type": "risk",
                        "triggered_rules": [{"rule": f"止损（浮亏 {pnl_pct:.1f}%）", "indicator": "pnl_pct", "current_value": round(pnl_pct, 2), "threshold": round(stop_loss_pct * 100, 1), "operator": "<="}],
                        "strategy_version": "stop_loss_auto_sell/v1.0",
                        "price_snapshot": {"close": round(cur_price, 4), "avg_cost": round(avg_cost, 4)},
                    },
                )
                if result.get('success'):
                    logger.info(f"✅ [{code}] 止损卖出成功：{qty}股")
                    sold_count += 1
                else:
                    logger.error(f"❌ [{code}] 止损卖出失败：{result.get('msg')}")
            except Exception as e:
                logger.error(f"❌ [{code}] 止损卖出异常：{e}")

    if sold_count == 0:
        logger.info("✅ 无触发止损的持仓")
    else:
        logger.info(f"✅ 本次共止损卖出 {sold_count} 只")
    return sold_count


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='止损自动卖出监控')
    parser.add_argument('--account-id', type=int, default=1, help='账户 ID（默认 1=学习账户）')
    parser.add_argument('--dry-run', action='store_true', help='仅检查，不实际卖出')
    args = parser.parse_args()

    if args.dry_run:
        # dry-run 模式：只打印，不卖出
        stop_loss_pct = load_stop_loss_pct()
        conn = get_conn()
        try:
            cur = conn.execute(
                "SELECT stock_code, stock_name, quantity, avg_cost, current_price, pnl_pct "
                "FROM sim_positions WHERE account_id = ? AND quantity > 0",
                (args.account_id,),
            )
            for row in cur.fetchall():
                code, name, qty, cost, price, pct = row
                flag = "🚨 触发止损" if pct is not None and pct <= stop_loss_pct * 100 else "✅ 正常"
                print(f"{flag} [{code}] {name} 浮亏 {pct:.2f}%" if pct is not None else f"⚠️  [{code}] {name} pnl_pct=None")
        finally:
            conn.close()
    else:
        check_and_sell(args.account_id)
