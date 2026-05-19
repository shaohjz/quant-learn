"""
端到端 mini-QMT 联调测试脚本

测试内容：
  1. 通过 broker.factory.get_broker("qmt", ...) 连接
  2. 查询账户和持仓
  3. 挂一个不会成交的低价买单（远低于现价）
  4. 等几秒看委托状态
  5. 撤单
  6. 再查一次持仓确认无副作用

⚠️ 必须先：启动 XtMiniQmt 并登录账号 90072426
⚠️ 全程使用模拟账户，不会动真钱
"""

import sys
import time
import logging
from datetime import datetime
from pathlib import Path

# 把 xtquant 路径放到 sys.path 最前面
sys.path.insert(0, r"D:\国金QMT交易端模拟\bin.x64\Lib\site-packages")
# 让脚本能找到 quant-learn 项目模块
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from broker.factory import get_broker

QMT_PATH = r"D:\国金QMT交易端模拟\userdata_mini"
QMT_ACCOUNT = "90072426"
SESSION_ID = 970520  # 用一个新的避免冲突

TEST_STOCK_CODE = "002156.SZ"   # 通富微电
TEST_STOCK_NAME = "通富微电"
TEST_PRICE = 30.00              # 远低于现价 ~58 元，不会成交
TEST_QTY = 100                  # 1 手


def hr(title=""):
    print("\n" + "=" * 60)
    if title:
        print(f"  {title}")
        print("=" * 60)


def main():
    hr("STEP 1: 连接 mini-QMT")
    broker = get_broker(
        "qmt",
        qmt_path=QMT_PATH,
        qmt_account=QMT_ACCOUNT,
        session_id=SESSION_ID,
        account_id=1,
    )
    print(f"  ✅ broker connected: {broker.name}, is_connected={broker.is_connected()}")

    try:
        hr("STEP 2: 查询账户资金")
        acc = broker.get_account()
        print(f"  现金:   {acc.cash:>15,.2f}")
        print(f"  市值:   {acc.market_value:>15,.2f}")
        print(f"  总资产: {acc.total_value:>15,.2f}")
        print(f"  额外:   {acc.extra}")

        hr("STEP 3: 查询持仓")
        poses = broker.get_positions()
        print(f"  持仓数量: {len(poses)}")
        for p in poses:
            print(f"  - {p.stock_code} {p.stock_name} 数量={p.quantity} "
                  f"成本={p.avg_cost:.3f} 现价={p.current_price:.3f} "
                  f"市值={p.market_value:.2f} 浮盈={p.pnl:+.2f} ({p.pnl_pct:+.2f}%)")

        hr(f"STEP 4: 挂一个不会成交的低价买单 ({TEST_STOCK_CODE} @ {TEST_PRICE} x {TEST_QTY})")
        result = broker.buy(
            stock_code=TEST_STOCK_CODE,
            price=TEST_PRICE,
            quantity=TEST_QTY,
            stock_name=TEST_STOCK_NAME,
            signal_reason="end-to-end test",
        )
        print(f"  下单结果: success={result.success}")
        print(f"  msg:      {result.msg}")
        print(f"  order_id: {result.order_id}")
        print(f"  amount:   {result.amount}")

        if not result.success:
            print("  ❌ 下单失败，跳过后续步骤")
            return

        hr("STEP 5: 等待 5 秒看委托状态")
        for i in range(5, 0, -1):
            print(f"  等待... {i}s", end="\r")
            time.sleep(1)
        print()

        hr("STEP 6: 撤单")
        cancel_result = broker.cancel(result.order_id)
        print(f"  撤单: success={cancel_result.success} msg={cancel_result.msg}")

        time.sleep(2)

        hr("STEP 7: 撤单后再查一次资金 + 持仓（应与初始一致）")
        acc2 = broker.get_account()
        print(f"  现金:   {acc2.cash:>15,.2f} (差额: {acc2.cash - acc.cash:+.2f})")
        print(f"  总资产: {acc2.total_value:>15,.2f} (差额: {acc2.total_value - acc.total_value:+.2f})")

        poses2 = broker.get_positions()
        print(f"  持仓数量: {len(poses2)} (变化: {len(poses2) - len(poses):+d})")

        hr("✅ 端到端测试完成")
        print(f"  完成时间: {datetime.now()}")

    finally:
        broker.disconnect()
        print("  broker disconnected")


if __name__ == "__main__":
    main()
