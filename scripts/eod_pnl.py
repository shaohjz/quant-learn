"""持仓收盘后浮赢亏计算 - 2026-05-18"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sim.realtime_price import get_latest_prices

POSITIONS = [
    {"code": "600330", "name": "天通股份", "qty": 400, "cost": 32.818},
    {"code": "002256", "name": "兆新股份", "qty": 700, "cost": 5.246},
    {"code": "002453", "name": "华软科技", "qty": 300, "cost": 6.467},
    {"code": "002342", "name": "巨力索具", "qty": 100, "cost": 19.680},
]

codes = [p["code"] for p in POSITIONS]
prices = get_latest_prices(codes)

print()
print("| 代码 | 名称 | 数量 | 成本价 | 收盘价 | 浮动盈亏 | 涨跌幅 |")
print("|---|---|---|---|---|---|---|")

total_cost = 0.0
total_market = 0.0
total_pnl = 0.0
for p in POSITIONS:
    code = p["code"]
    qty = p["qty"]
    cost = p["cost"]
    px = prices.get(code, {}).get("price", 0) or 0
    cost_amt = qty * cost
    mkt = qty * px
    pnl = mkt - cost_amt
    pct = (px - cost) / cost * 100 if cost else 0
    total_cost += cost_amt
    total_market += mkt
    total_pnl += pnl
    sign = "+" if pnl >= 0 else ""
    print(f"| {code} | {p['name']} | {qty} | {cost:.3f} | {px:.2f} | {sign}{pnl:.2f} | {sign}{pct:.2f}% |")

total_pct = total_pnl / total_cost * 100 if total_cost else 0
sign = "+" if total_pnl >= 0 else ""
print(f"| **合计** | - | - | {total_cost:.2f} | {total_market:.2f} | **{sign}{total_pnl:.2f}** | **{sign}{total_pct:.2f}%** |")
