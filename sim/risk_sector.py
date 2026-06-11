"""
sim/risk_sector.py — 行业/板块集中度风控

功能：
  1. 计算持仓的行业/板块分布（市值占比）
  2. 检查是否超过 config.yaml 中配置的阈值
  3. 提供买入前的集中度预检查（买入后是否超标）
  4. 生成集中度报告（用于日报/告警）

依赖：
  - scripts/fetch_sector.py  获取股票行业归属（带缓存）
  - sim/portfolio.py        读取持仓
  - sim/config.py          读取 risk.max_industry_pct / risk.max_sector_pct
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sim.config import get, risk_params
from sim.portfolio import load_real_holdings, fetch_account, real_account_id


# ============================================================
# 阈值配置（从 config.yaml 读取，带默认值）
# ============================================================

def _max_industry_pct() -> float:
    """单行业最大持仓占比（占总资产），默认 0.30"""
    return float(get("risk.max_industry_pct", 0.30))


def _max_sector_pct() -> float:
    """单板块最大持仓占比（占总资产），默认 0.35"""
    return float(get("risk.max_sector_pct", 0.35))


def _warn_industry_pct() -> float:
    """行业集中度警告阈值，默认 0.25"""
    return float(get("risk.warn_industry_pct", 0.25))


def _warn_sector_pct() -> float:
    """板块集中度警告阈值，默认 0.30"""
    return float(get("risk.warn_sector_pct", 0.30))


# ============================================================
# 行业/板块数据加载
# ============================================================

def _load_sector_cache() -> dict:
    """加载 scripts/fetch_sector.py 生成的缓存"""
    cache_file = ROOT / "data" / "sector_cache.json"
    if not cache_file.exists():
        return {}
    import json
    with open(cache_file, "r", encoding="utf-8") as f:
        cache = json.load(f)
    return cache.get("data", {})


def load_holdings_with_sector() -> list[dict]:
    """
    加载持仓，并附加 industry / sector 字段。

    行业来源（优先级从高到低）：
      1. config.yaml 中 watchlist.user_manual[code].tags（已有手工标注）
      2. scripts/fetch_sector.py 生成的缓存（AKShare 数据）
      3. config.yaml 中 real_portfolio_rules[code] 的上下文推断

    返回 list of {
        "code": ..., "name": ..., "qty": ..., "cost": ...,
        "current": ..., "market_value": ...,
        "industry": ..., "sector": ..., "concepts": [...],
    }
    """
    holdings = load_real_holdings()
    cache = _load_sector_cache()

    # 加载 config.yaml 中的 tags 信息
    try:
        from sim.config import load_config
        cfg = load_config()
        watchlist = (cfg.get("watchlist") or {}).get("user_manual", {}) or {}
        real_rules = cfg.get("real_portfolio_rules", {}) or {}
    except Exception:
        watchlist = {}
        real_rules = {}

    result = []
    for h in holdings:
        qty = h.get("qty", 0)
        current = h.get("current", h.get("cost", 0))
        market_value = qty * current

        code = h.get("code", "").zfill(6)

        # 优先级1：config.yaml tags
        wl_entry = watchlist.get(code, {}) or {}
        tags = wl_entry.get("tags", []) or []
        ind_from_tags = tags[0] if tags else ""  # 取第一个 tag 作为行业

        # 优先级2：AKShare 缓存
        sec_info = cache.get(code, {})
        ind_from_cache = sec_info.get("industry", "")
        sec_from_cache = sec_info.get("sector", "")

        industry = ind_from_tags or ind_from_cache or ""
        # sector：优先用 tags 第二个元素，否则用缓存
        if len(tags) >= 2:
            sector = tags[1]
        else:
            sector = sec_from_cache or ""

        result.append({
            **h,
            "market_value": market_value,
            "industry": industry,
            "sector": sector,
            "concepts": tags[2:] if len(tags) > 2 else sec_info.get("concepts", []),
        })
    return result


# ============================================================
# 集中度计算
# ============================================================

def compute_concentration(holdings: list[dict] | None = None) -> dict:
    """
    计算行业/板块集中度。

    返回：
    {
        "by_industry": {industry: {"mv": ..., "pct": ...}},
        "by_sector":  {sector:    {"mv": ..., "pct": ...}},
        "total_mv": ...,
        "total_assets": ...,
        "warnings": [...],
        "violations": [...],
    }
    """
    if holdings is None:
        holdings = load_holdings_with_sector()

    acc = fetch_account(real_account_id()) or {}
    total_assets = float(acc.get("total_value", 1))

    by_industry: dict[str, float] = defaultdict(float)
    by_sector: dict[str, float] = defaultdict(float)
    unknown_industry_mv = 0.0
    unknown_sector_mv = 0.0
    total_mv = 0.0

    for h in holdings:
        mv = h.get("market_value", 0)
        total_mv += mv
        ind = h.get("industry", "").strip()
        sec = h.get("sector", "").strip()

        if ind:
            by_industry[ind] += mv
        else:
            unknown_industry_mv += mv
        if sec:
            by_sector[sec] += mv
        else:
            unknown_sector_mv += mv

    # 转成 pct 并排序
    ind_items = sorted(
        [(k, {"mv": v, "pct": v / total_assets}) for k, v in by_industry.items()],
        key=lambda x: -x[1]["mv"],
    )
    sec_items = sorted(
        [(k, {"mv": v, "pct": v / total_assets}) for k, v in by_sector.items()],
        key=lambda x: -x[1]["mv"],
    )

    # 检查阈值
    warnings = []
    violations = []

    max_ind_pct = _max_industry_pct()
    warn_ind_pct = _warn_industry_pct()
    max_sec_pct = _max_sector_pct()
    warn_sec_pct = _warn_sector_pct()

    for ind, info in ind_items:
        pct = info["pct"]
        if pct >= max_ind_pct:
            violations.append(f"🚨 行业「{ind}」占比 {pct*100:.1f}% 超过上限 {max_ind_pct*100:.0f}%")
        elif pct >= warn_ind_pct:
            warnings.append(f"⚠️ 行业「{ind}」占比 {pct*100:.1f}% 接近上限 {max_ind_pct*100:.0f}%")

    for sec, info in sec_items:
        pct = info["pct"]
        if pct >= max_sec_pct:
            violations.append(f"🚨 板块「{sec}」占比 {pct*100:.1f}% 超过上限 {max_sec_pct*100:.0f}%")
        elif pct >= warn_sec_pct:
            warnings.append(f"⚠️ 板块「{sec}」占比 {pct*100:.1f}% 接近上限 {max_sec_pct*100:.0f}%")

    if unknown_industry_mv / total_assets > 0.10:
        warnings.append(
            f"⚠️ 有 {unknown_industry_mv:,.0f} 元（{unknown_industry_mv/total_assets*100:.1f}%）"
            f"持仓无法识别行业，建议运行 `python scripts/fetch_sector.py` 更新"
        )

    return {
        "by_industry": dict(ind_items),
        "by_sector": dict(sec_items),
        "unknown_industry_mv": unknown_industry_mv,
        "unknown_sector_mv": unknown_sector_mv,
        "total_mv": total_mv,
        "total_assets": total_assets,
        "warnings": warnings,
        "violations": violations,
    }


# ============================================================
# 买入前预检查
# ============================================================

def check_before_buy(
    stock_code: str,
    buy_qty: int,
    buy_price: float,
    holdings: list[dict] | None = None,
) -> dict:
    """
    买入前检查：买入后行业/板块集中度是否会超标。

    返回：
    {
        "ok": bool,
        "warnings": [...],
        "violations": [...],
        "sector_after": {...},  # 买入后该票的板块/行业占比
    }
    """
    if holdings is None:
        holdings = load_holdings_with_sector()

    acc = fetch_account(real_account_id()) or {}
    total_assets = float(acc.get("total_value", 1))
    buy_mv = buy_qty * buy_price

    # 先从 config.yaml tags 获取行业（优先），再从缓存补充
    from sim.config import load_config
    cfg = load_config()
    watchlist = (cfg.get("watchlist") or {}).get("user_manual", {}) or {}
    code_6 = stock_code.zfill(6)
    wl_entry = watchlist.get(code_6, {}) or {}
    tags = wl_entry.get("tags", []) or []
    new_industry = tags[0] if tags else ""
    new_sector = tags[1] if len(tags) >= 2 else ""

    # 如果 tags 没有，再尝试 AKShare 缓存
    if not new_industry or not new_sector:
        cache = _load_sector_cache()
        sec_info = cache.get(code_6, {})
        if not new_industry:
            new_industry = sec_info.get("industry", "")
        if not new_sector:
            new_sector = sec_info.get("sector", "")

    # 计算买入后的行业/板块市值
    by_industry: dict[str, float] = defaultdict(float)
    by_sector: dict[str, float] = defaultdict(float)

    for h in holdings:
        mv = h.get("market_value", 0)
        ind = h.get("industry", "").strip()
        sec = h.get("sector", "").strip()
        if ind:
            by_industry[ind] += mv
        if sec:
            by_sector[sec] += mv

    for h in holdings:
        mv = h.get("market_value", 0)
        ind = h.get("industry", "").strip()
        sec = h.get("sector", "").strip()
        if ind:
            by_industry[ind] += mv
        if sec:
            by_sector[sec] += mv

    # 加上买入金额
    if new_industry:
        by_industry[new_industry] += buy_mv
    if new_sector:
        by_sector[new_sector] += buy_mv

    # 检查
    warnings = []
    violations = []

    max_ind_pct = _max_industry_pct()
    max_sec_pct = _max_sector_pct()

    if new_industry and by_industry.get(new_industry, 0) / total_assets >= max_ind_pct:
        violations.append(
            f"🚨 买入后行业「{new_industry}」占比 "
            f"{by_industry[new_industry]/total_assets*100:.1f}% 将超过上限 {max_ind_pct*100:.0f}%"
        )
    if new_sector and by_sector.get(new_sector, 0) / total_assets >= max_sec_pct:
        violations.append(
            f"🚨 买入后板块「{new_sector}」占比 "
            f"{by_sector[new_sector]/total_assets*100:.1f}% 将超过上限 {max_sec_pct*100:.0f}%"
        )

    # 警告（接近但未超过）
    warn_ind_pct = _warn_industry_pct()
    warn_sec_pct = _warn_sector_pct()
    if new_industry and by_industry.get(new_industry, 0) / total_assets >= warn_ind_pct:
        if by_industry[new_industry] / total_assets < max_ind_pct:
            warnings.append(
                f"⚠️ 买入后行业「{new_industry}」占比 "
                f"{by_industry[new_industry]/total_assets*100:.1f}% 接近上限 {max_ind_pct*100:.0f}%"
            )
    if new_sector and by_sector.get(new_sector, 0) / total_assets >= warn_sec_pct:
        if by_sector[new_sector] / total_assets < max_sec_pct:
            warnings.append(
                f"⚠️ 买入后板块「{new_sector}」占比 "
                f"{by_sector[new_sector]/total_assets*100:.1f}% 接近上限 {max_sec_pct*100:.0f}%"
            )

    return {
        "ok": len(violations) == 0,
        "warnings": warnings,
        "violations": violations,
        "new_industry": new_industry,
        "new_sector": new_sector,
        "buy_mv": buy_mv,
        "pct_after": {
            "industry": by_industry.get(new_industry, 0) / total_assets if new_industry else 0,
            "sector": by_sector.get(new_sector, 0) / total_assets if new_sector else 0,
        },
    }


# ============================================================
# 报告生成
# ============================================================

def format_concentration_report(conc: dict | None = None) -> str:
    """生成可读性好的集中度报告（用于企微推送/日志）"""
    if conc is None:
        conc = compute_concentration()

    lines = []
    lines.append("📊 持仓行业/板块集中度分析")
    lines.append("=" * 50)

    total_assets = conc["total_assets"]
    total_mv = conc["total_mv"]
    lines.append(f"总资产: ¥{total_assets:,.2f}  持仓市值: ¥{total_mv:,.2f}  "
                f"仓位: {total_mv/total_assets*100:.1f}%")
    lines.append("")

    # 行业分布
    lines.append("【行业分布】")
    for ind, info in conc["by_industry"].items():
        bar_len = int(info["pct"] * 50)
        bar = "█" * bar_len + "░" * (50 - bar_len)
        lines.append(f"  {ind:<12s} {bar} {info['pct']*100:5.1f}%  ¥{info['mv']:>10,.0f}")
    if conc["unknown_industry_mv"] > 0:
        lines.append(
            f"  (未识别)         ¥{conc['unknown_industry_mv']:>10,.0f}  "
            f"{conc['unknown_industry_mv']/total_assets*100:5.1f}%"
        )
    lines.append("")

    # 板块分布
    lines.append("【板块分布】")
    for sec, info in conc["by_sector"].items():
        bar_len = int(info["pct"] * 50)
        bar = "█" * bar_len + "░" * (50 - bar_len)
        lines.append(f"  {sec:<8s} {bar} {info['pct']*100:5.1f}%  ¥{info['mv']:>10,.0f}")
    if conc["unknown_sector_mv"] > 0:
        lines.append(
            f"  (未识别)   ¥{conc['unknown_sector_mv']:>10,.0f}  "
            f"{conc['unknown_sector_mv']/total_assets*100:5.1f}%"
        )
    lines.append("")

    # 警告/违规
    if conc["violations"]:
        lines.append("【🚨 违规（超过阈值）】")
        for v in conc["violations"]:
            lines.append(f"  {v}")
        lines.append("")
    if conc["warnings"]:
        lines.append("【⚠️ 警告（接近阈值）】")
        for w in conc["warnings"]:
            lines.append(f"  {w}")
        lines.append("")

    if not conc["violations"] and not conc["warnings"]:
        lines.append("✅ 行业/板块集中度正常，无超标风险")

    lines.append("=" * 50)
    return "\n".join(lines)


# ============================================================
# 公共接口：更新行业缓存（供外部调用）
# ============================================================

def ensure_sector_data(stock_codes: list[str] | None = None) -> int:
    """
    确保行业数据已获取。如果缓存缺失或过期，自动调用 fetch_sector.py 更新。
    返回更新了的股票数量。
    """
    import subprocess
    root = str(ROOT)
    script = str(ROOT / "scripts" / "fetch_sector.py")
    if stock_codes:
        codes_str = " ".join(stock_codes)
        cmd = [sys.executable, script] + stock_codes
    else:
        cmd = [sys.executable, script]

    print(f"[risk_sector] 更新行业缓存: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        capture_output=True, text=True, timeout=120, cwd=root,
    )
    if result.returncode != 0:
        print(f"  ⚠️  fetch_sector 返回非 0: {result.stderr[:200]}")
        return 0
    return 1


# ============================================================
# CLI
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="行业/板块集中度分析")
    parser.add_argument("--fetch", action="store_true", help="先更新行业缓存")
    parser.add_argument("--codes", nargs="*", help="额外指定股票代码")
    args = parser.parse_args()

    if args.fetch:
        codes = args.codes if args.codes else None
        ensure_sector_data(codes)
        return

    conc = compute_concentration()
    report = format_concentration_report(conc)
    print(report)


if __name__ == "__main__":
    main()
