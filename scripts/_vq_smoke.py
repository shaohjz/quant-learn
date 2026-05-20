"""smoke test: vqlearn.gateways.qmt_data"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vqlearn.gateways.qmt_data import QmtDataGateway
import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# 持仓 + 部分观察池
CODES = ["600330", "002256", "002453", "603601",
         "002428", "600130", "603178", "603986",
         "002032", "600999", "601598", "300346"]

g = QmtDataGateway()
g.connect()

print(f"\n[1] download history (last 60 days)")
g.download_history(CODES, period="1d", start_time="20260301")
print(f"[2] pull last 5 daily bars per code")
result = g.get_kline(CODES, period="1d", count=5)
for code, df in result.items():
    if df is None or df.empty:
        print(f"  ❌ {code} EMPTY")
        continue
    last = df.iloc[-1]
    print(f"  ✓ {code:12s} close={last['close']:.2f} vol={last['volume']:.0f} {df.index[-1]}")

print(f"\n[3] full tick:")
ticks = g.get_tick(CODES)
for code, t in (ticks or {}).items():
    print(f"  {code:12s} last={t.get('lastPrice'):.2f} bid={t.get('bidPrice', [0])[0]:.2f} ask={t.get('askPrice', [0])[0]:.2f}")
