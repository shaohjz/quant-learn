"""
mini-QMT 正确用法 smoke test
- 直接拉历史 K 线（无需订阅）
- 拉账户/持仓（XtQuantTrader）
"""
from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
import time
import sys

# ---- 1. xtdata：拉 K 线 ----
print(f"[1] xtdata: reconnect to localhost:58600")
xtdata.reconnect("localhost", 58600)
print("    OK")

print(f"\n[2] download history daily kline for 600330.SH")
try:
    xtdata.download_history_data("600330.SH", period="1d", start_time="20260401", end_time="")
    print("    download OK")
except Exception as e:
    print(f"    download fail: {e}")

print(f"\n[3] pull recent kline (10 daily bars):")
try:
    df = xtdata.get_market_data_ex(
        field_list=["open", "high", "low", "close", "volume"],
        stock_list=["600330.SH"],
        period="1d",
        count=10
    )
    for code, frame in df.items():
        print(f"  {code}:")
        print(frame.tail(10) if hasattr(frame, "tail") else frame)
except Exception as e:
    print(f"    kline pull fail: {e}")

# ---- 2. xttrader：连交易接口 ----
print(f"\n[4] XtQuantTrader: connect mini-QMT trader")

class MyCb(XtQuantTraderCallback):
    def on_connected(self):
        print("    [cb] connected to QMT")
    def on_disconnected(self):
        print("    [cb] disconnected")
    def on_account_status(self, status):
        print(f"    [cb] account status: {status}")

USERDATA_MINI = r"D:\国金QMT交易端模拟\userdata_mini"
session_id = int(time.time())
trader = XtQuantTrader(USERDATA_MINI, session_id)
trader.register_callback(MyCb())
trader.start()
ret = trader.connect()
print(f"    connect ret = {ret} (0=success)")

if ret != 0:
    print("    可能未启动 mini-QMT 或 userdata 路径不对")
    sys.exit(1)

# ---- 3. 用国金账号 ----
print(f"\n[5] subscribe + query account")
# userdata_mini/users 里看到的账户号：704121 / 970520 / 970525
for acct_no in ["704121", "970520", "970525"]:
    acc = StockAccount(acct_no)
    sub_ret = trader.subscribe(acc)
    print(f"  acct={acct_no} subscribe ret={sub_ret}")
    asset = trader.query_stock_asset(acc)
    if asset:
        print(f"    {acct_no} cash={asset.cash:.2f} market_value={asset.market_value:.2f} total={asset.total_asset:.2f}")
    positions = trader.query_stock_positions(acc)
    if positions:
        print(f"    {acct_no} positions ({len(positions)}):")
        for p in positions[:10]:
            print(f"      {p.stock_code} qty={p.volume} avail={p.can_use_volume} cost={p.open_price:.3f} pnl={p.market_value:.2f}")

print("\n[OK] smoke test done.")
