"""
scripts/test_qmt_e2e_v2.py — QMT mini 端到端测试（dry-run 安全模式）

流程：
  1. 加载 config.local.yaml
  2. 创建 QMTBroker（dry_run=true，不真连 QMT，不真下单）
  3. 拉账户 / 拉持仓
  4. 模拟下 1 笔买入（FAKE 委托号）
  5. 断开

❗ 严禁切到 dry_run=false 或者改成真实账户 8890461376 跑这个脚本。
   如果哪天真要切，必须 1) 启动 QMT mini 客户端、2) account_id == 90072426、
   3) 人在终端旁手动审核后再做。
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml
from datetime import date

from broker.factory import get_broker
from broker.base import OrderSide


def load_cfg() -> dict:
    cfg_path = ROOT / "config.local.yaml"
    if not cfg_path.exists():
        raise SystemExit(f"找不到 {cfg_path}")
    return yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}


def main():
    cfg = load_cfg()
    live = (cfg.get("broker") or {}).get("live") or {}

    qmt_path = live.get("qmt_path")
    qmt_account = live.get("qmt_account")
    session_id = int(live.get("session_id", 970515))
    dry_run = bool(live.get("dry_run", True))
    xtquant_sp = live.get("xtquant_site_packages")

    print("=" * 70)
    print(f"QMT mini 端到端测试")
    print(f"  qmt_path        : {qmt_path}")
    print(f"  account         : {qmt_account}")
    print(f"  session_id      : {session_id}")
    print(f"  dry_run         : {dry_run}")
    print(f"  xtquant_site_pkg: {xtquant_sp}")
    print("=" * 70)

    if str(qmt_account) == "8890461376":
        raise SystemExit("⛔ 拒绝：检测到真实账户 8890461376，停止")

    if not dry_run:
        ans = input("⚠️ dry_run=false 会真下单！输入 YES_I_KNOW 继续：").strip()
        if ans != "YES_I_KNOW":
            raise SystemExit("已取消")

    print("\n[1] connect ...")
    broker = get_broker(
        mode="live",
        qmt_path=qmt_path,
        qmt_account=qmt_account,
        session_id=session_id,
        dry_run=dry_run,
        xtquant_site_packages=xtquant_sp,
    )
    print(f"  connected = {broker.is_connected()}")

    try:
        print("\n[2] get_account ...")
        acc = broker.get_account()
        print(f"  cash={acc.cash:,.2f}  market_value={acc.market_value:,.2f}  total={acc.total_value:,.2f}")

        print("\n[3] get_positions ...")
        pos = broker.get_positions()
        if not pos:
            print("  （空仓 / dry-run 默认空仓）")
        for p in pos:
            print(f"  {p.stock_code} {p.stock_name} qty={p.quantity} avg={p.avg_cost:.2f} pnl={p.pnl:+.2f}")

        print("\n[4] dry-run buy 100 股 600519 @ 1500.00 ...")
        result = broker.buy(
            stock_code="600519",
            price=1500.00,
            quantity=100,
            stock_name="贵州茅台",
            signal_reason="qmt_e2e_v2 自检",
            trade_date=date.today(),
        )
        print(f"  success={result.success} order_id={result.order_id} extra={result.extra}")

        print("\n[5] dry-run sell 200 股 600330 @ 30.00 ...")
        result2 = broker.sell(
            stock_code="600330",
            price=30.00,
            quantity=200,
            stock_name="天通股份",
            signal_reason="qmt_e2e_v2 自检（卖测试）",
            trade_date=date.today(),
        )
        print(f"  success={result2.success} order_id={result2.order_id} extra={result2.extra}")

    finally:
        print("\n[6] disconnect ...")
        broker.disconnect()
        print(f"  connected = {broker.is_connected()}")

    print("\n✅ 测试完成。" + ("（dry-run 模式，未真下单）" if dry_run else "（live 模式，请检查 QMT 委托）"))


if __name__ == "__main__":
    main()
