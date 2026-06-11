"""Asset allocation and dynamic strategy exposure helpers (REQ-031).

This module keeps the allocation logic deterministic and data-source agnostic so it
can be reused by the web dashboard and the daily review without depending on live
market APIs.  It answers two related questions:

1. What does the account currently own by broad asset class / strategy bucket?
2. Given a market-regime snapshot, should the account reduce or increase risk?
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class RegimePolicy:
    label: str
    target_position_pct: float
    min_cash_pct: float
    strategy_targets: dict[str, float]
    reason: str


REGIME_POLICIES: dict[str, RegimePolicy] = {
    "strong": RegimePolicy(
        label="偏强",
        target_position_pct=70.0,
        min_cash_pct=20.0,
        strategy_targets={"低吸": 30.0, "网格": 25.0, "趋势/突破": 25.0, "打板/强势": 15.0, "主观/手动": 5.0},
        reason="市场宽度/涨停扩散偏强，可提高进攻型策略占用。",
    ),
    "neutral": RegimePolicy(
        label="中性",
        target_position_pct=50.0,
        min_cash_pct=35.0,
        strategy_targets={"低吸": 35.0, "网格": 35.0, "趋势/突破": 20.0, "打板/强势": 5.0, "主观/手动": 5.0},
        reason="市场信号未形成明显方向，维持半仓并以低吸/网格为主。",
    ),
    "weak": RegimePolicy(
        label="偏弱",
        target_position_pct=30.0,
        min_cash_pct=55.0,
        strategy_targets={"低吸": 35.0, "网格": 45.0, "趋势/突破": 15.0, "打板/强势": 0.0, "主观/手动": 5.0},
        reason="市场偏弱或跌停扩散，降低总仓位并暂停高波动打板/追涨。",
    ),
    "unknown": RegimePolicy(
        label="数据不足",
        target_position_pct=40.0,
        min_cash_pct=45.0,
        strategy_targets={"低吸": 35.0, "网格": 40.0, "趋势/突破": 15.0, "打板/强势": 0.0, "主观/手动": 10.0},
        reason="市场数据不足，按防守口径保留现金冗余。",
    ),
}


LOW_BUY_WORDS = ("低吸", "buy_zone", "强买", "跌破", "回踩", "低位", "阈值")
GRID_WORDS = ("网格", "grid", "均值", "震荡")
MOMENTUM_WORDS = ("趋势", "突破", "trend", "break", "breakout", "放量")
CHASE_WORDS = ("打板", "涨停", "追涨", "强势", "momentum")
MANUAL_WORDS = ("手动", "manual", "用户", "实盘镜像", "user_real_position")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        v = float(value)
        return default if v != v else v
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def classify_asset_class(position: dict[str, Any]) -> str:
    """Classify a holding into a broad allocation bucket.

    The rules intentionally rely on stable fields (code/name/sector/industry) and
    avoid external security metadata.  They can be overridden later by adding an
    ``asset_class`` field in imported positions/config.
    """
    explicit = str(position.get("asset_class") or "").strip()
    if explicit:
        return explicit

    code = str(position.get("stock_code") or position.get("code") or "")
    name = str(position.get("stock_name") or position.get("name") or "")
    sector = str(position.get("sector") or "")
    industry = str(position.get("industry") or "")
    text = f"{name} {sector} {industry}".lower()

    if any(w in text for w in ("债", "货币", "现金", "逆回购", "固收", "bond", "money market")) or code.startswith(("511", "204", "1318")):
        return "固收/现金管理"
    if code.startswith(("510", "512", "513", "515", "516", "159", "588", "56", "15", "16")) or "etf" in text or "基金" in text:
        return "宽基/行业ETF"
    if any(w in text for w in ("主观", "手动", "manual")):
        return "主观持仓"
    return "个股量化"


def _parse_context(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        obj = json.loads(str(raw))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def classify_strategy_bucket(position: dict[str, Any], latest_buy: dict[str, Any] | None = None) -> str:
    """Classify holding exposure by strategy style."""
    latest_buy = latest_buy or {}
    ctx = _parse_context(latest_buy.get("trade_context"))
    parts = [
        position.get("strategy"),
        position.get("strategy_tag"),
        latest_buy.get("strategy_name"),
        ctx.get("strategy"),
        ctx.get("rule_level"),
        ctx.get("buy_type"),
        ctx.get("sell_reason"),
        latest_buy.get("signal_reason"),
    ]
    text = " ".join(str(p) for p in parts if p).lower()
    if any(w.lower() in text for w in MANUAL_WORDS):
        return "主观/手动"
    if any(w.lower() in text for w in CHASE_WORDS):
        return "打板/强势"
    if any(w.lower() in text for w in MOMENTUM_WORDS):
        return "趋势/突破"
    if any(w.lower() in text for w in GRID_WORDS):
        return "网格"
    if any(w.lower() in text for w in LOW_BUY_WORDS):
        return "低吸"
    return "未标记/规则"


def infer_market_regime(market: Any) -> str:
    """Infer strong/neutral/weak/unknown from a MarketSentiment-like object."""
    if market is None:
        return "unknown"
    data = asdict(market) if hasattr(market, "__dataclass_fields__") else dict(market)
    label = str(data.get("risk_label") or "")
    if "偏弱" in label or "跌停" in label:
        return "weak"
    if "偏强" in label or "活跃" in label:
        return "strong"
    if "数据不足" in label:
        return "unknown"

    up = data.get("up_count")
    down = data.get("down_count")
    if up is not None and down is not None and (_safe_float(up) + _safe_float(down) > 0):
        ratio = _safe_float(up) / max(_safe_float(up) + _safe_float(down), 1.0)
        if ratio >= 0.60:
            return "strong"
        if ratio <= 0.40:
            return "weak"

    lu = data.get("limit_up_count")
    ld = data.get("limit_down_count")
    if lu is not None and ld is not None:
        lu_f, ld_f = _safe_float(lu), _safe_float(ld)
        if ld_f >= max(20.0, lu_f * 0.8):
            return "weak"
        if lu_f >= max(50.0, ld_f * 3.0 + 1.0):
            return "strong"
    return "neutral"


def _latest_buy_by_code(trades: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for t in sorted(trades, key=lambda x: str(x.get("created_at") or x.get("trade_date") or "")):
        if str(t.get("direction") or "").upper() != "BUY":
            continue
        code = str(t.get("stock_code") or "")
        if code:
            latest[code] = t
    return latest


def summarize_allocation(
    account: dict[str, Any] | None,
    positions: list[dict[str, Any]],
    trades: list[dict[str, Any]] | None = None,
    market: Any | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return allocation dashboard data for one account."""
    account = account or {}
    trades = trades or []
    config = config or {}
    latest_buy = _latest_buy_by_code(trades)

    cash = _safe_float(account.get("cash"))
    total_mv = 0.0
    class_totals: defaultdict[str, float] = defaultdict(float)
    strategy_totals: defaultdict[str, float] = defaultdict(float)
    position_rows: list[dict[str, Any]] = []

    for p in positions or []:
        qty = _safe_int(p.get("quantity"))
        if qty <= 0:
            continue
        mv = _safe_float(p.get("market_value"))
        if mv <= 0:
            mv = _safe_float(p.get("current_price")) * qty
        total_mv += mv
        asset_class = classify_asset_class(p)
        strategy = classify_strategy_bucket(p, latest_buy.get(str(p.get("stock_code") or "")))
        class_totals[asset_class] += mv
        strategy_totals[strategy] += mv
        position_rows.append({
            "code": str(p.get("stock_code") or p.get("code") or ""),
            "name": str(p.get("stock_name") or p.get("name") or ""),
            "market_value": round(mv, 2),
            "asset_class": asset_class,
            "strategy_bucket": strategy,
        })

    total_asset = cash + total_mv
    if total_asset <= 0:
        total_asset = _safe_float(account.get("total_value")) or _safe_float(account.get("initial_cash"))

    def rows_from_totals(totals: dict[str, float], denom: float) -> list[dict[str, Any]]:
        rows = []
        for name, value in sorted(totals.items(), key=lambda kv: kv[1], reverse=True):
            rows.append({"name": name, "value": round(value, 2), "pct": round(value / denom * 100, 1) if denom > 0 else 0.0})
        return rows

    asset_rows = rows_from_totals(class_totals, total_asset)
    if cash > 0 or not asset_rows:
        asset_rows.append({"name": "现金", "value": round(cash, 2), "pct": round(cash / total_asset * 100, 1) if total_asset > 0 else 0.0})

    strategy_rows = rows_from_totals(strategy_totals, max(total_mv, 1.0))
    regime = infer_market_regime(market)
    policy = REGIME_POLICIES[regime]
    current_position_pct = round(total_mv / total_asset * 100, 1) if total_asset > 0 else 0.0
    current_cash_pct = round(cash / total_asset * 100, 1) if total_asset > 0 else 0.0
    diff = round(current_position_pct - policy.target_position_pct, 1)

    advice: list[str] = []
    if diff > 5:
        advice.append(f"当前仓位 {current_position_pct:.1f}% 高于{policy.label}目标 {policy.target_position_pct:.0f}%，建议调降约 {diff:.1f} 个百分点。")
    elif diff < -10:
        advice.append(f"当前仓位 {current_position_pct:.1f}% 低于{policy.label}目标 {policy.target_position_pct:.0f}%，可等待确认信号后分批提高约 {abs(diff):.1f} 个百分点。")
    else:
        advice.append(f"当前仓位 {current_position_pct:.1f}% 接近{policy.label}目标区间，暂以持仓质量筛选为主。")
    if current_cash_pct < policy.min_cash_pct:
        advice.append(f"现金水位 {current_cash_pct:.1f}% 低于建议下限 {policy.min_cash_pct:.0f}%，优先减少弱势/超配仓位。")
    if regime in {"weak", "unknown"}:
        advice.append("弱市/数据不足时暂停打板追涨，新增仓位优先低吸、网格或ETF分散。")

    # Strategy over/under weight versus policy targets (relative to current market value).
    strategy_target_rows = []
    strategy_pct = {r["name"]: r["pct"] for r in strategy_rows}
    for name, target in policy.strategy_targets.items():
        cur = float(strategy_pct.get(name, 0.0))
        strategy_target_rows.append({"name": name, "current_pct": round(cur, 1), "target_pct": round(target, 1), "diff_pct": round(cur - target, 1)})

    return {
        "account_id": account.get("id"),
        "total_asset": round(total_asset, 2),
        "cash": round(cash, 2),
        "total_market_value": round(total_mv, 2),
        "position_pct": current_position_pct,
        "cash_pct": current_cash_pct,
        "asset_classes": asset_rows,
        "strategy_buckets": strategy_rows,
        "strategy_targets": strategy_target_rows,
        "positions": position_rows,
        "market_regime": regime,
        "regime_policy": asdict(policy),
        "advice": advice,
    }


def render_allocation_markdown(allocation: dict[str, Any], compact: bool = False) -> str:
    """Render allocation summary for daily review / WeCom."""
    if not allocation:
        return ""
    policy = allocation.get("regime_policy") or {}
    title = "### 🧩 大类资产配置与策略配比"
    if compact:
        advice = (allocation.get("advice") or [""])[0]
        return (
            f"🧩 配置：仓位 {allocation.get('position_pct', 0)}% / 目标 {policy.get('target_position_pct', 0):.0f}% "
            f"({policy.get('label', 'N/A')})；{advice}"
        )

    lines = [title]
    lines.append(
        f"- 市场环境：**{policy.get('label', 'N/A')}**；目标仓位 {policy.get('target_position_pct', 0):.0f}% / 最低现金 {policy.get('min_cash_pct', 0):.0f}%"
    )
    lines.append(f"- 当前：总资产 ¥{allocation.get('total_asset', 0):,.0f}，仓位 {allocation.get('position_pct', 0):.1f}% / 现金 {allocation.get('cash_pct', 0):.1f}%")
    lines.append("- 大类资产：" + "；".join(f"{r['name']} {r['pct']:.1f}%" for r in allocation.get("asset_classes", [])))
    if allocation.get("strategy_buckets"):
        lines.append("- 策略占用：" + "；".join(f"{r['name']} {r['pct']:.1f}%" for r in allocation.get("strategy_buckets", [])))
    lines.append("- 动态建议：")
    for item in allocation.get("advice", []):
        lines.append(f"  - {item}")
    lines.append("")
    return "\n".join(lines)
