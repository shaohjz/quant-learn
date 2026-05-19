import sys, time, random
sys.path.insert(0, r"D:\国金QMT交易端模拟\bin.x64\Lib\site-packages")
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount

session = random.randint(100000, 999999)
print(f"session: {session}")

class CB(XtQuantTraderCallback):
    def on_disconnected(self):
        print("[CB] DISCONNECTED")

t = XtQuantTrader(r"D:\国金QMT交易端模拟\userdata_mini", session)
t.register_callback(CB())
t.start()
time.sleep(2)

ret = t.connect()
print(f"connect ret = {ret}")

if ret == 0:
    acc = StockAccount("90072426")
    sub = t.subscribe(acc)
    print(f"subscribe = {sub}")

    asset = t.query_stock_asset(acc)
    if asset:
        print(f"\n=== 账户 90072426 ===")
        print(f"  总资产: {asset.total_asset:.2f}")
        print(f"  现金:   {asset.cash:.2f}")
        print(f"  市值:   {asset.market_value:.2f}")
        print(f"  冻结:   {asset.frozen_cash:.2f}")

    poses = t.query_stock_positions(acc)
    print(f"\n=== 持仓 ({len(poses) if poses else 0}) ===")
    if poses:
        for p in poses:
            print(f"  {p.stock_code:12s} 数量={p.volume} 可用={p.can_use_volume} 成本={p.open_price:.3f}")
    t.stop()
    print("\n✅ 全部成功！")
else:
    print("\n❌ connect 仍然失败")
    print("提示：mini-QMT 启动后第一次连接可能需要等数据加载完成（30-60秒）")
