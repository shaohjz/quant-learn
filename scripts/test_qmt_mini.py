import sys
sys.path.insert(0, r'D:\国金QMT交易端模拟\bin.x64\Lib\site-packages')
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount

qmt_path = r'D:\国金QMT交易端模拟\userdata_mini'
trader = XtQuantTrader(qmt_path, 970520)

class CB(XtQuantTraderCallback):
    def on_disconnected(self): pass
    def on_stock_order(self, order): pass
    def on_stock_trade(self, trade): pass
    def on_order_error(self, e): pass
    def on_cancel_error(self, e): pass

trader.register_callback(CB())
trader.start()
ret = trader.connect()
print(f'connect={ret}')
if ret == 0:
    acc = StockAccount('90072426')
    sub = trader.subscribe(acc)
    print(f'subscribe={sub}')
    asset = trader.query_stock_asset(acc)
    if asset:
        print(f'cash={asset.cash}')
        print(f'total={asset.total_asset}')
        print(f'market_value={asset.market_value}')
    else:
        print('asset is None')
    poses = trader.query_stock_positions(acc) or []
    print(f'positions: {len(poses)}')
    for p in poses:
        print(f'  {p.stock_code} qty={p.volume} can_use={p.can_use_volume} avg={p.open_price}')
trader.stop()
print('DONE')
