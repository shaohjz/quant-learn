"""
scripts/generate_next_watchlist.py — 生成下个交易日关注股票池

目标：把盘后复盘/策略留痕转成「明日重点监控」清单，避免次日盘前没有
明确关注池。默认只写文件，不改观察池配置；需要自动接入阈值监控时传
--update-auto，把候选写入 config_auto.yaml 的 auto_discovered。

输入来源（按优先级融合）：
  1. review_decisions：当天被风控拦截/允许的买入候选，代表策略曾经看中；
  2. sim_trades：当天有成交的股票，次日需要跟踪执行结果；
  3. sim_positions：当前持仓，次日需要继续监控；
  4. 既有 watchlist：延续用户手动/系统观察池。

用法：
  python scripts/generate_next_watchlist.py
  python scripts/generate_next_watchlist.py --source-date 2026-06-01 --target-date 2026-06-02
  python scripts/generate_next_watchlist.py --update-auto --push
"""
from __future__ import annotations

import argparse
import json
import io
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

# Windows GBK 兼容：强制 stdout 使用 UTF-8
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sim_live_mirror.db"
CONFIG_AUTO_PATH = ROOT / "config_auto.yaml"
OUT_DIR = ROOT / "output" / "next_watchlists"
DATA_DIR = ROOT / "data" / "next_watchlists"

sys.path.insert(0, str(ROOT))
from sim.portfolio import load_watchlist_rules  # noqa: E402
from sim.trade_calendar import next_trading_day, prev_trading_day  # noqa: E402


@dataclass
class Candidate:
    code: str
    name: str = ""
    category: str = "strategy_candidate"
    priority: int = 50
    reasons: list[str] = field(default_factory=list)
    last_price: float | None = None
    source_refs: list[str] = field(default_factory=list)

    def add_reason(self, reason: str, ref: str | None = None, priority: int | None = None) -> None:
        reason = (reason or "").strip()
        if reason and reason not in self.reasons:
            self.reasons.append(reason)
        if ref and ref not in self.source_refs:
            self.source_refs.append(ref)
        if priority is not None:
            self.priority = max(self.priority, priority)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "category": self.category,
            "priority": self.priority,
            "last_price": self.last_price,
            "reasons": self.reasons,
            "source_refs": self.source_refs,
        }


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _latest_date(conn: sqlite3.Connection) -> str:
    dates: list[str] = []
    if _table_exists(conn, "review_decisions"):
        dates += [r[0] for r in conn.execute("SELECT DISTINCT trade_date FROM review_decisions WHERE trade_date IS NOT NULL")]
    if _table_exists(conn, "sim_trades"):
        dates += [r[0] for r in conn.execute("SELECT DISTINCT substr(trade_date,1,10) FROM sim_trades WHERE trade_date IS NOT NULL")]
    return max(dates) if dates else date.today().isoformat()


def _upsert(pool: dict[str, Candidate], code: str, **kwargs: Any) -> Candidate:
    code = str(code).zfill(6)
    cand = pool.get(code)
    if cand is None:
        cand = Candidate(code=code)
        pool[code] = cand
    for key, value in kwargs.items():
        if value in (None, ""):
            continue
        if key == "priority":
            cand.priority = max(cand.priority, int(value))
        elif key == "name" and not cand.name:
            cand.name = str(value)
        elif key == "last_price" and cand.last_price is None:
            cand.last_price = float(value)
        elif key == "category":
            # 保留更具体/更高优先级来源
            if cand.category == "strategy_candidate" or kwargs.get("priority", 0) >= cand.priority:
                cand.category = str(value)
    return cand


def collect_candidates(source_date: str, db_path: Path = DB_PATH, include_existing_watchlist: bool = True) -> list[Candidate]:
    """收集并融合候选，返回按 priority 降序排列的关注池。"""
    pool: dict[str, Candidate] = {}
    conn = _connect(db_path)
    try:
        # 1) 复盘/风控决策：策略想买但被规则挡住的票，次日值得继续看。
        if _table_exists(conn, "review_decisions"):
            rows = conn.execute(
                """
                SELECT stock_code, decision_type, allowed, reason, created_at
                  FROM review_decisions
                 WHERE trade_date=?
                 ORDER BY created_at DESC, id DESC
                """,
                (source_date,),
            ).fetchall()
            for r in rows:
                allowed = int(r["allowed"] or 0)
                dtype = r["decision_type"] or "decision"
                priority = 90 if allowed else 82
                category = "blocked_buy_candidate" if not allowed else "approved_signal"
                cand = _upsert(pool, r["stock_code"], category=category, priority=priority)
                prefix = "策略信号被风控拦截" if not allowed else "策略信号通过"
                cand.add_reason(f"{prefix}: {dtype}；{r['reason'] or ''}".rstrip("；"), "review_decisions", priority)

        # 2) 当日成交：次日需要验证买卖后的走势/风控状态。
        if _table_exists(conn, "sim_trades"):
            rows = conn.execute(
                """
                SELECT stock_code, stock_name, direction, price, quantity, signal_reason, trade_time
                  FROM sim_trades
                 WHERE substr(trade_date,1,10)=?
                 ORDER BY id DESC
                """,
                (source_date,),
            ).fetchall()
            for r in rows:
                direction = (r["direction"] or "").upper()
                priority = 78 if direction == "BUY" else 72
                category = "post_trade_followup"
                cand = _upsert(
                    pool, r["stock_code"], name=r["stock_name"], last_price=r["price"],
                    category=category, priority=priority,
                )
                cand.add_reason(
                    f"{source_date} {direction} {int(r['quantity'] or 0)}股 @ {float(r['price'] or 0):.3f}；{r['signal_reason'] or '次日跟踪成交效果'}",
                    "sim_trades",
                    priority,
                )

        # 3) 当前持仓：持仓是天然的次日监控对象，亏损/盈利扩大的优先级更高。
        if _table_exists(conn, "sim_positions"):
            rows = conn.execute(
                """
                SELECT stock_code, stock_name, quantity, avg_cost, current_price, pnl_pct, account_id
                  FROM sim_positions
                 WHERE quantity > 0
                 ORDER BY ABS(COALESCE(pnl_pct,0)) DESC, market_value DESC
                """
            ).fetchall()
            for r in rows:
                pnl_pct = float(r["pnl_pct"] or 0)
                priority = 70 + min(15, int(abs(pnl_pct)))
                cand = _upsert(
                    pool, r["stock_code"], name=r["stock_name"], last_price=r["current_price"],
                    category="holding_monitor", priority=priority,
                )
                cand.add_reason(
                    f"当前持仓 {int(r['quantity'] or 0)}股，成本 {float(r['avg_cost'] or 0):.3f}，浮盈亏 {pnl_pct:+.2f}%",
                    "sim_positions",
                    priority,
                )
    finally:
        conn.close()

    # 4) 既有观察池：延续关注，但优先级低于当天新增信号/持仓。
    if include_existing_watchlist:
        try:
            for code, body in load_watchlist_rules(include_disabled=False).items():
                cand = _upsert(pool, code, name=body.get("name", ""), category="existing_watchlist", priority=55)
                cat = body.get("category", "watchlist")
                reason = body.get("added_reason") or body.get("notes") or f"既有观察池({cat})"
                cand.add_reason(reason, "watchlist", 55)
        except Exception as exc:
            # 生成关注池不能因为配置读取失败整体中断。
            print(f"⚠ 读取既有观察池失败：{exc}")

    # 没有名称时用代码兜底。
    for cand in pool.values():
        if not cand.name:
            cand.name = cand.code

    return sorted(pool.values(), key=lambda c: (-c.priority, c.code))


def enrich_missing_names_prices(candidates: list[Candidate]) -> None:
    """用非实时安全后退行情补齐名称/价格；失败不影响主流程。"""
    missing = [c.code for c in candidates if not c.name or c.name == c.code or c.last_price is None]
    if not missing:
        return
    try:
        from sim.realtime_price import get_latest_prices_with_fallback
        prices = get_latest_prices_with_fallback(sorted(set(missing)))
    except Exception as exc:
        print(f"⚠ 补齐候选名称/价格失败：{exc}")
        return
    for c in candidates:
        data = prices.get(c.code) or {}
        name = data.get("name")
        price = data.get("price")
        if name and (not c.name or c.name == c.code):
            c.name = str(name)
        if price and c.last_price is None:
            c.last_price = float(price)


def render_markdown(source_date: str, target_date: str, candidates: list[Candidate], limit: int = 20) -> str:
    lines = [
        f"# 📌 下个交易日关注股票池：{target_date}",
        "",
        f"来源交易日：{source_date}；生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"候选数量：{len(candidates)}（展示前 {min(limit, len(candidates))}）",
        "",
    ]
    if not candidates:
        lines.append("暂无候选。")
        return "\n".join(lines)

    category_names = {
        "blocked_buy_candidate": "🟠 被风控拦截的策略候选",
        "approved_signal": "🟢 已通过策略信号",
        "post_trade_followup": "🔁 成交后跟踪",
        "holding_monitor": "📦 持仓监控",
        "existing_watchlist": "👀 既有观察池",
        "strategy_candidate": "📈 策略候选",
    }
    shown = candidates[:limit]
    for idx, c in enumerate(shown, 1):
        cat = category_names.get(c.category, c.category)
        price = f" @ {c.last_price:.3f}" if c.last_price is not None else ""
        lines.append(f"{idx}. **{c.name}**({c.code}){price}｜{cat}｜P{c.priority}")
        for reason in c.reasons[:2]:
            lines.append(f"   - {reason}")
    if len(candidates) > limit:
        lines.append(f"\n... 还有 {len(candidates) - limit} 只，详见 JSON 文件。")
    lines.append("\n> 说明：该清单用于次日盘前/盘中监控，不等于买入建议；实际交易仍需风控确认。")
    return "\n".join(lines)


def _load_config_auto(path: Path = CONFIG_AUTO_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"auto_discovered": {}, "cooldown": {}}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"auto_discovered": {}, "cooldown": {}}


def _save_config_auto(cfg: dict[str, Any], path: Path = CONFIG_AUTO_PATH) -> None:
    path.write_text(yaml.dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _rules_for_candidate(c: Candidate) -> dict[str, dict[str, Any]]:
    if c.last_price and c.last_price > 0:
        buy_zone = round(c.last_price * 0.97, 2)
        buy_strong = round(c.last_price * 0.93, 2)
        trend_break = round(c.last_price * 0.85, 2)
    else:
        buy_zone = buy_strong = trend_break = 0
    return {
        "buy_zone": {"trigger": buy_zone, "dir": "below", "msg": f"💰 {c.name} 回踩至 {buy_zone}，进入次日关注区"},
        "buy_strong": {"trigger": buy_strong, "dir": "below", "msg": f"💰💰 {c.name} 跌至 {buy_strong}，强关注区"},
        "trend_break": {"trigger": trend_break, "dir": "below", "msg": f"⚠️ {c.name} 跌破 {trend_break}，次日关注失效"},
    }


def update_auto_watchlist(candidates: list[Candidate], target_date: str, top: int = 10, path: Path = CONFIG_AUTO_PATH) -> int:
    """把高优先级候选写入 config_auto.yaml:auto_discovered。返回新增数量。"""
    cfg = _load_config_auto(path)
    auto = cfg.setdefault("auto_discovered", {})
    added = 0
    for c in candidates[:top]:
        if c.code in auto:
            continue
        auto[c.code] = {
            "name": c.name,
            "enabled": True,
            "source": "next_watchlist",
            "added_at": date.today().isoformat(),
            "target_date": target_date,
            "added_by": "generate_next_watchlist",
            "added_reason": "；".join(c.reasons[:2]),
            "discovery_score": c.priority,
            "signal_type": c.category,
            "last_alert_at": None,
            "alert_count": 0,
            "max_inactive_days": 3,
            "tags": ["next_day"],
            "rules": _rules_for_candidate(c),
        }
        added += 1
    _save_config_auto(cfg, path)
    return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成下个交易日关注股票池")
    parser.add_argument("--source-date", help="复盘来源日期，默认取 DB 最新交易日期")
    parser.add_argument("--target-date", help="目标交易日，默认 source-date 的下一交易日")
    parser.add_argument("--top", type=int, default=20, help="报告展示/JSON主列表数量")
    parser.add_argument("--update-auto", action="store_true", help="写入 config_auto.yaml:auto_discovered")
    parser.add_argument("--auto-top", type=int, default=10, help="写入 auto_discovered 的最大数量")
    parser.add_argument("--no-existing-watchlist", action="store_true", help="不合并既有观察池")
    parser.add_argument("--push", action="store_true", help="生成后推送企微 webhook")
    args = parser.parse_args(argv)

    with _connect(DB_PATH) as conn:
        source_date = args.source_date or _latest_date(conn)
    target_date = args.target_date or next_trading_day(datetime.fromisoformat(source_date).date()).isoformat()

    candidates = collect_candidates(
        source_date=source_date,
        db_path=DB_PATH,
        include_existing_watchlist=not args.no_existing_watchlist,
    )
    enrich_missing_names_prices(candidates)
    markdown = render_markdown(source_date, target_date, candidates, limit=args.top)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    md_path = OUT_DIR / f"{target_date}.md"
    json_path = DATA_DIR / f"{target_date}.json"
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps({
        "source_date": source_date,
        "target_date": target_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "candidates": [c.to_dict() for c in candidates],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    added = 0
    if args.update_auto:
        added = update_auto_watchlist(candidates, target_date=target_date, top=args.auto_top)

    if args.push:
        from sim.notifier import send_markdown
        send_markdown(markdown[:3500])

    print(f"✅ 已生成 {target_date} 关注池：{len(candidates)} 只")
    print(f"   Markdown: {md_path}")
    print(f"   JSON:     {json_path}")
    if args.update_auto:
        print(f"   auto_discovered 新增: {added} 只")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
