import sys
sys.path.insert(0, r"D:\国金QMT交易端模拟\bin.x64\Lib\site-packages")
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount

# QMT 在 mini 模式下，userdata_mini 通常是 userdata 目录本身
# 国金这版没有 userdata_mini，我们试 userdata
qmt_path = r"D:\国金QMT交易端模拟\userdata"

print(f"qmt_path: {qmt_path}")
session_id = 970518
trader = XtQuantTrader(qmt_path, session_id)

class CB(XtQuantTraderCallback):
    def on_disconnected(self): print("[CB] disconnected")
    def on_stock_order(self, order): print(f"[CB] order: {order}")
    def on_stock_trade(self, trade): print(f"[CB] trade: {trade}")
    def on_order_error(self, e): print(f"[CB] order_error: {e}")
    def on_cancel_error(self, e): print(f"[CB] cancel_error: {e}")
    def on_order_stock_async_response(self, r): print(f"[CB] async_resp: {r}")

trader.register_callback(CB())
trader.start()

print("正在连接 QMT...")
ret = trader.connect()
print(f"connect return: {ret}  (0=成功)")

if ret == 0:
    acc = StockAccount("90072426")
    sub = trader.subscribe(acc)
    print(f"subscribe return: {sub}  (0=成功)")
    
    # 查询资金
    asset = trader.query_stock_asset(acc)
    if asset:
        print(f"\n=== 账户资金 ===")
        print(f"  总资产: {asset.total_asset}")
        print(f"  现金: {asset.cash}")
        print(f"  市值: {asset.market_value}")
        print(f"  冻结: {asset.frozen_cash}")
    else:
        print("查询资金失败")
    
    # 查询持仓
    poses = trader.query_stock_positions(acc)
    print(f"\n=== 持仓 ({len(poses) if poses else 0} 只) ===")
    if poses:
        for p in poses:
            print(f"  {p.stock_code:10s}  数量={p.volume:>5}  可用={p.can_use_volume:>5}  成本={p.open_price:.3f}")
    
    trader.stop()
    print("\n✅ 连接测试成功")
else:
    print(f"\n❌ 连接失败 (ret={ret})")
    print("可能原因：")
    print("  1. userdata_mini 路径不对")
    print("  2. QMT 客户端未登录账号")
    print("  3. session_id 冲突")
