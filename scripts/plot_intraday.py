"""画 2026-05-18 当日 7 只股票分时走势图"""
import json
from pathlib import Path
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 中文字体
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(r"C:\Users\Administrator\.openclaw\workspace\quant-learn")
LOG = ROOT / "output" / "intraday_log.jsonl"
TARGET_DATE = "2026-05-18"

CODES = ["600330", "002256", "002453", "002709", "002149", "002342", "002156"]
NAMES = {
    "600330": "天通股份",
    "002256": "兆新股份",
    "002453": "华软科技",
    "002709": "天赐材料",
    "002149": "西部材料",
    "002342": "巨力索具",
    "002156": "通富微电",
}

# 收集 ts 格式的记录
series = {c: {"t": [], "p": []} for c in CODES}
with LOG.open("r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        ts = obj.get("ts")
        prices = obj.get("prices")
        if not ts or not prices:
            continue
        if not ts.startswith(TARGET_DATE):
            continue
        try:
            tt = datetime.fromisoformat(ts)
        except Exception:
            continue
        for code in CODES:
            if code in prices:
                p = prices[code]
                if isinstance(p, dict):
                    p = p.get("price")
                if p is None:
                    continue
                series[code]["t"].append(tt)
                series[code]["p"].append(float(p))

fig, axes = plt.subplots(3, 3, figsize=(15, 10), constrained_layout=True)
axes = axes.flatten()

for i, code in enumerate(CODES):
    ax = axes[i]
    ts = series[code]["t"]
    ps = series[code]["p"]
    if ts:
        ax.plot(ts, ps, color="#d62728", linewidth=1.6, marker="o", markersize=2.5)
        first = ps[0]
        last = ps[-1]
        chg_pct = (last - first) / first * 100 if first else 0
        color = "#d62728" if last >= first else "#2ca02c"
        ax.set_title(f"{code} {NAMES[code]}  {last:.2f} ({chg_pct:+.2f}%)",
                     fontsize=11, color=color)
        ax.axhline(first, color="gray", linestyle="--", linewidth=0.6, alpha=0.6)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.tick_params(axis="x", labelsize=8)
        ax.tick_params(axis="y", labelsize=8)
        ax.grid(True, alpha=0.3)
    else:
        ax.set_title(f"{code} {NAMES[code]}  无数据", fontsize=11)
        ax.axis("off")

# 隐藏多余的两个子图
for j in range(len(CODES), len(axes)):
    axes[j].axis("off")

fig.suptitle(f"分时走势 - {TARGET_DATE}", fontsize=14, fontweight="bold")
out = ROOT / "output" / f"intraday_{TARGET_DATE}.png"
fig.savefig(out, dpi=120)
print(f"saved: {out}")
print("数据点统计:")
for c in CODES:
    print(f"  {c} {NAMES[c]}: {len(series[c]['t'])} 个采样点")
