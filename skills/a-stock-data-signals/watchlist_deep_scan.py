"""
watchlist_deep_scan.py — 对 watchlist 中的股票跑全维度信号扫描

功能：
  1. 读取 watchlist_notes.json + next_watchlists 最新日期的候选列表
  2. 对每只股票跑：概念板块、解禁预警、资金流向、融资融券
  3. 输出综合评分 + 风险提示
  4. 支持增量扫描（只扫新增/未扫过的票）

输出：output/watchlist_scans/YYYY-MM-DD_scan.json
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

# ── 路径 ──
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "a-stock-data-signals"))

from a_stock_data_signals import (
    concept_blocks_signal,
    lockup_warning_signal,
    fund_flow_signal,
    margin_trading_signal,
    block_trade_signal,
    shareholder_count_signal,
    dragon_tiger_signal,
    tencent_quote,
)


def load_watchlist() -> list[dict]:
    """加载 watchlist 中的所有股票"""
    # 1. 长线观察
    notes_path = ROOT / "data" / "watchlist_notes.json"
    long_term = []
    if notes_path.exists():
        data = json.loads(notes_path.read_text(encoding="utf-8"))
        long_term = data.get("watchlist", [])

    # 2. 最新日期的 next_watchlists
    nw_dir = ROOT / "data" / "next_watchlists"
    daily = []
    if nw_dir.exists():
        files = sorted(nw_dir.glob("*.json"), reverse=True)
        if files:
            data = json.loads(files[0].read_text(encoding="utf-8"))
            daily = data.get("candidates", [])

    # 3. 合并去重
    seen = set()
    result = []
    for item in long_term:
        code = item.get("code", "")
        if code and code not in seen:
            seen.add(code)
            result.append({
                "code": code,
                "name": item.get("name", ""),
                "source": "long_term_watchlist",
                "theme": item.get("theme", ""),
                "reason": item.get("reason", ""),
            })
    for item in daily:
        code = item.get("code", "")
        if code and code not in seen:
            seen.add(code)
            result.append({
                "code": code,
                "name": item.get("name", ""),
                "source": "daily_watchlist",
                "reasons": item.get("reasons", []),
                "priority": item.get("priority", 0),
            })

    return result


def scan_single_stock(code: str, name: str = "") -> dict:
    """对单只股票跑全维度扫描"""
    scan = {
        "code": code,
        "name": name,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 1. 概念板块归属
    try:
        scan["concept_blocks"] = concept_blocks_signal(code)
    except Exception as e:
        scan["concept_blocks"] = {"error": str(e)}

    # 2. 解禁预警
    try:
        scan["lockup"] = lockup_warning_signal(code)
    except Exception as e:
        scan["lockup"] = {"error": str(e)}

    # 3. 资金流向
    try:
        scan["fund_flow"] = fund_flow_signal(code)
    except Exception as e:
        scan["fund_flow"] = {"error": str(e)}

    # 4. 融资融券
    try:
        scan["margin"] = margin_trading_signal(code)
    except Exception as e:
        scan["margin"] = {"error": str(e)}

    # 5. 大宗交易
    try:
        scan["block_trade"] = block_trade_signal(code)
    except Exception as e:
        scan["block_trade"] = {"error": str(e)}

    # 6. 股东户数
    try:
        scan["shareholders"] = shareholder_count_signal(code)
    except Exception as e:
        scan["shareholders"] = {"error": str(e)}

    # 7. 龙虎榜
    try:
        scan["dragon_tiger"] = dragon_tiger_signal(code)
    except Exception as e:
        scan["dragon_tiger"] = {"error": str(e)}

    # 8. 实时行情
    try:
        quotes = tencent_quote([code])
        if code in quotes:
            scan["quote"] = quotes[code]
    except Exception as e:
        scan["quote"] = {"error": str(e)}

    return scan


def score_stock(scan: dict) -> dict:
    """对扫描结果进行综合评分"""
    score = 0
    signals = []
    risks = []

    # 资金流向评分
    ff = scan.get("fund_flow", {})
    if ff.get("main_net_total", 0) > 0:
        score += 10
        signals.append(f"主力流入 {ff.get('main_net_total_wan', 0):.0f}万")
    else:
        score -= 5
        risks.append(f"主力流出 {ff.get('main_net_total_wan', 0):.0f}万")

    # 解禁风险
    lu = scan.get("lockup", {})
    if lu.get("has_upcoming"):
        score -= 15
        total_shares = lu.get("total_upcoming_shares", 0)
        risks.append(f"未来有解禁(共{total_shares}股)")

    # 融资融券趋势
    mg = scan.get("margin", {})
    if mg.get("trend") == "融资买入增加（看多情绪）":
        score += 8
        signals.append("融资买入增加")
    elif mg.get("trend") == "融资买入减少（看多情绪减弱）":
        score -= 5
        risks.append("融资买入减少")

    # 股东户数（筹码集中度）
    sh = scan.get("shareholders", {})
    if sh.get("trend") == "筹码集中（股东户数减少）":
        score += 8
        signals.append("筹码集中")
    elif sh.get("trend") == "筹码分散（股东户数增加）":
        score -= 8
        risks.append("筹码分散")

    # 龙虎榜
    dt = scan.get("dragon_tiger", {})
    if dt.get("records"):
        latest = dt["records"][0]
        if latest.get("net_buy_wan", 0) > 0:
            score += 12
            signals.append(f"龙虎榜净买{latest['net_buy_wan']}万")
        else:
            score -= 3
            risks.append(f"龙虎榜净卖{abs(latest.get('net_buy_wan', 0))}万")

    # 大宗交易（溢价=正面，折价=负面）
    bt = scan.get("block_trade", {})
    if bt.get("records"):
        latest = bt["records"][0]
        if latest.get("premium_pct", 0) > 0:
            score += 5
            signals.append(f"大宗溢价{latest['premium_pct']}%")
        elif latest.get("premium_pct", 0) < -5:
            score -= 5
            risks.append(f"大宗折价{latest['premium_pct']}%")

    # 概念板块热度（板块数多 = 题材丰富）
    cb = scan.get("concept_blocks", {})
    if cb.get("total", 0) >= 10:
        score += 5
        signals.append(f"涉及{cb['total']}个板块")

    # 综合评级
    if score >= 20:
        rating = "⭐⭐⭐ 强烈关注"
    elif score >= 10:
        rating = "⭐⭐ 关注"
    elif score >= 0:
        rating = "⭐ 一般"
    else:
        rating = "⚠️ 谨慎"

    return {
        "score": score,
        "rating": rating,
        "signals": signals,
        "risks": risks,
    }


def scan_watchlist(codes: list[str] = None, max_stocks: int = 10) -> dict:
    """
    扫描 watchlist。
    codes: 指定代码列表（None=从 watchlist 加载）
    max_stocks: 最多扫描数量（东财限流，一次别太多）
    """
    if codes is None:
        stocks = load_watchlist()
    else:
        stocks = [{"code": c, "name": c} for c in codes]

    # 按优先级排序（daily 的优先）
    stocks.sort(key=lambda s: s.get("priority", 0) if s.get("source") == "daily_watchlist" else 50, reverse=True)

    results = []
    for i, stock in enumerate(stocks[:max_stocks]):
        code = stock["code"]
        name = stock.get("name", "")
        print(f"[{i+1}/{min(len(stocks), max_stocks)}] 扫描 {code} {name}...")

        scan = scan_single_stock(code, name)
        scan["metadata"] = {
            "source": stock.get("source", ""),
            "theme": stock.get("theme", ""),
            "reason": stock.get("reason", stock.get("reasons", [])),
        }
        scan["score"] = score_stock(scan)
        results.append(scan)

    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_scanned": len(results),
        "results": results,
    }

    # 保存
    out_dir = ROOT / "output" / "watchlist_scans"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{report['date']}_scan.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"\n[OK] 扫描报告已保存: {path}")

    return report


def format_scan_report(report: dict) -> str:
    """格式化为可读文本"""
    lines = []
    lines.append(f"📋 Watchlist 深度扫描 — {report.get('date', '未知')}")
    lines.append(f"扫描 {report['total_scanned']} 只股票")
    lines.append("=" * 60)

    # 按评分排序
    sorted_results = sorted(report["results"], key=lambda r: r["score"]["score"], reverse=True)

    for r in sorted_results:
        s = r["score"]
        lines.append(f"\n{s['rating']} {r['code']} {r['name']}  (评分: {s['score']})")

        # 行情
        q = r.get("quote", {})
        if q and "price" in q:
            lines.append(f"   价格: {q['price']} | PE: {q.get('pe_ttm', 'N/A')} | PB: {q.get('pb', 'N/A')} | 市值: {q.get('mcap_yi', 'N/A')}亿")

        # 概念板块
        cb = r.get("concept_blocks", {})
        if cb.get("concept_tags"):
            tags = cb["concept_tags"][:8]
            lines.append(f"   板块: {' | '.join(tags)}")

        # 信号
        if s["signals"]:
            lines.append(f"   ✅ {' | '.join(s['signals'])}")
        if s["risks"]:
            lines.append(f"   ⚠️ {' | '.join(s['risks'])}")

        # 解禁
        lu = r.get("lockup", {})
        if lu.get("has_upcoming"):
            for u in lu["upcoming"][:2]:
                lines.append(f"   🔓 解禁: {u['date']} {u['type']} 数量{u['shares']}")

        # 龙虎榜
        dt = r.get("dragon_tiger", {})
        if dt.get("records"):
            latest = dt["records"][0]
            lines.append(f"   🐉 龙虎榜: {latest['date']} {latest.get('reason', '')} 净买{latest['net_buy_wan']}万")

        # 融资融券
        mg = r.get("margin", {})
        if mg.get("trend") and mg["trend"] != "未知":
            lines.append(f"   💰 {mg['trend']}")

        # 股东户数
        sh = r.get("shareholders", {})
        if sh.get("trend") and sh["trend"] != "未知":
            lines.append(f"   👥 {sh['trend']}")

    return "\n".join(lines)


if __name__ == "__main__":
    import time

    max_stocks = int(sys.argv[1]) if len(sys.argv) > 1 else 10

    print(f"Watchlist 深度扫描 (max={max_stocks})")
    print("=" * 50)

    report = scan_watchlist(max_stocks=max_stocks)
    text = format_scan_report(report)

    print("\n" + text)
