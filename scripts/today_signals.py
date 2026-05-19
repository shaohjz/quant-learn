"""
今日实时策略信号 - 看每只持仓+观察股的当前买卖建议
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.signal_generator import generate_signals

# 持仓
HOLDINGS = [
    {"code": "002256", "name": "兆新股份", "qty": 700, "cost": 5.246},
    {"code": "002453", "name": "华软科技", "qty": 300, "cost": 6.467},
    {"code": "600330", "name": "天通股份", "qty": 400, "cost": 32.818},
    {"code": "002342", "name": "巨力索具", "qty": 100, "cost": 19.680},
]

# 观察股
WATCHLIST = [
    {"code": "002709", "name": "天赐材料"},
    {"code": "002149", "name": "西部材料"},
    {"code": "002156", "name": "通富微电"},
]

def fmt_signal(s):
    """信号 dict 格式化"""
    if not s:
        return "  (无信号数据)"
    out = []
    for k, v in s.items():
        if k in ("stock_code", "stock_name"):
            continue
        out.append(f"    {k}: {v}")
    return "\n".join(out)


print("=" * 80)
print("  📊 今日策略信号  -", "持仓股")
print("=" * 80)
for h in HOLDINGS:
    pos = {"quantity": h["qty"], "avg_cost": h["cost"]}
    try:
        sig = generate_signals(h["code"], h["name"], existing_position=pos)
        print(f"\n▶ {h['name']} ({h['code']}) 持仓 {h['qty']} @ ¥{h['cost']:.3f}")
        print(fmt_signal(sig))
    except Exception as e:
        print(f"\n▶ {h['name']} ({h['code']}): ❌ {type(e).__name__}: {e}")

print("\n" + "=" * 80)
print("  📊 今日策略信号  -", "观察股")
print("=" * 80)
for w in WATCHLIST:
    try:
        sig = generate_signals(w["code"], w["name"])
        print(f"\n▶ {w['name']} ({w['code']})")
        print(fmt_signal(sig))
    except Exception as e:
        print(f"\n▶ {w['name']} ({w['code']}): ❌ {type(e).__name__}: {e}")

print("\n" + "=" * 80)
print("✅ 全部完成")
