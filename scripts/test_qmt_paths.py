import sys, os
sys.path.insert(0, r"D:\国金QMT交易端模拟\bin.x64\Lib\site-packages")
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount

paths = [
    r"D:\国金QMT交易端模拟\userdata_mini",
    r"D:\国金QMT交易端模拟\userdata\users\90072426",
    r"D:\国金QMT交易端模拟\userdata",
    r"D:\国金QMT交易端模拟",
    r"D:\国金QMT交易端模拟\bin.x64",
]

import random
session = random.randint(100000, 999999)
print(f"session_id: {session}")

class CB(XtQuantTraderCallback):
    def on_disconnected(self): pass

for p in paths:
    print(f"\n=== 尝试路径: {p}  exists={os.path.exists(p)} ===")
    if not os.path.exists(p):
        continue
    try:
        t = XtQuantTrader(p, session)
        t.register_callback(CB())
        t.start()
        ret = t.connect()
        print(f"  connect ret = {ret}")
        if ret == 0:
            print(f"  ✅ 成功！userdata_mini 路径: {p}")
            t.stop()
            break
        t.stop()
    except Exception as e:
        print(f"  ERR: {type(e).__name__}: {e}")
    session += 1
