"""scripts/daily_close_report.py — 收盘交易日报（双账户 + NAV 回写）

推送 #1 模拟学习仓 + #3 波段仓。当日盈亏 = 今日总值 − 昨日 NAV（禁止再写死 10 万基准）。
REQ-069/REQ-071: 每日收盘前回写 acc1 + acc3 的 sim_daily_nav 行，复盘日報区分建仓贡献与持仓浮动盈亏。

用法：
  python scripts/daily_close_report.py
  python scripts/daily_close_report.py --no-push
  python scripts/daily_close_report.py --date 2026-07-15 --no-push
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.config_resolver import resolve_artifact_root, resolve_db_path

OUTPUT_DIR = resolve_artifact_root()
DB_PATH = resolve_db_path()

logger = logging.getLogger("daily_close")

# 主人约定：日常盯学习仓 + 通用波段 + 银行波段
ACCOUNTS = (
    {"id": 1, "label": "模拟学习仓", "short": "学习"},
    {"id": 3, "label": "波段模拟仓", "short": "波段"},
    {"id": 4, "label": "银行波段仓", "short": "银行"},
)


def _load_webhook() -> str:
    try:
        import yaml

        for rel, keys in (
            ("config.local.yaml", (("notify", "wecom_webhook"), ("notifier", "wecom_webhook"))),
            ("config.yaml", (("notify", "wecom_webhook"),)),
        ):
            path = ROOT / rel
            if not path.exists():
                continue
            cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for a, b in keys:
                url = ((cfg.get(a) or {}).get(b) or "").strip()
                if url and "***" not in url and "YOUR_KEY" not in url:
                    return url
        return (os.environ.get("WECOM_WEBHOOK") or "").strip()
    except Exception:
        return ""


def push_webhook(content: str) -> bool:
    url = _load_webhook()
    if not url:
        print("❌ Webhook URL 未配置")
        return False
    import urllib.request

    payload = json.dumps(
        {"msgtype": "markdown", "markdown": {"content": content}},
        ensure_ascii=False,
    ).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        resp = urllib.request.urlopen(req, timeout=10).read().decode()
        ok = '"errcode":0' in resp
        print("✅ 收盘日报推送成功" if ok else f"⚠️ 推送返回异常: {resp}")
        return ok
    except Exception as e:
        print(f"❌ 推送失败: {e}")
        return False


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def prev_nav_total(conn: sqlite3.Connection, account_id: int, trade_date: str) -> float | None:
    row = conn.execute(
        "SELECT total_value FROM sim_daily_nav WHERE account_id=? AND trade_date<? "
        "ORDER BY trade_date DESC LIMIT 1",
        (account_id, trade_date),
    ).fetchone()
    if row and row[0] is not None:
        return _f(row[0])
    return None


def prev_nav_row(conn: sqlite3.Connection, account_id: int, trade_date: str) -> dict | None:
    """获取前一交易日完整 NAV 行，含 cumulative_return 和 max_drawdown。"""
    row = conn.execute(
        "SELECT total_value, cumulative_return, max_drawdown "
        "FROM sim_daily_nav WHERE account_id=? AND trade_date<? "
        "ORDER BY trade_date DESC LIMIT 1",
        (account_id, trade_date),
    ).fetchone()
    if not row:
        return None
    return {
        "total": _f(row[0]),
        "cum_ret": _f(row[1]),
        "max_dd": _f(row[2]),
    }


# ── REQ-069/REQ-071: NAV 回写 ──────────────────────────────────────────────

def compute_account_snapshot(conn: sqlite3.Connection, account_id: int) -> dict:
    """
    从 sim_account + sim_positions 计算真实 snapshot：
    - cash: sim_account.cash
    - market_value: SUM(sim_positions.market_value WHERE quantity > 0)
    - total_value: cash + market_value
    """
    acct = conn.execute(
        "SELECT cash, total_value, initial_cash FROM sim_account WHERE id=?",
        (account_id,),
    ).fetchone()
    if not acct:
        return {"cash": 0.0, "market_value": 0.0, "total": 0.0, "initial": 0.0}

    cash = _f(acct[0])
    initial = _f(acct[2])

    # REQ-069: market_value 列脏/0 时回退 qty*price/cost
    mv_row = conn.execute(
        "SELECT COALESCE(SUM("
        "  CASE "
        "    WHEN COALESCE(market_value, 0) > 0 THEN market_value "
        "    ELSE quantity * COALESCE(NULLIF(current_price, 0), NULLIF(avg_cost, 0), 0) "
        "  END"
        "), 0) "
        "FROM sim_positions WHERE account_id=? AND quantity > 0",
        (account_id,),
    ).fetchone()
    market_value = _f(mv_row[0]) if mv_row else 0.0

    total = cash + market_value
    return {"cash": cash, "market_value": market_value, "total": total, "initial": initial}


def write_account_nav(conn: sqlite3.Connection, account_id: int, trade_date: str) -> dict | None:
    """
    REQ-069: 将当日账户净值回写到 sim_daily_nav。
    同时计算 daily_return / cumulative_return / max_drawdown。
    幂等：使用 INSERT OR REPLACE。
    返回写入的快照 dict；如果账户不存在则返回 None。
    """
    snap = compute_account_snapshot(conn, account_id)
    if snap["total"] <= 0 and snap["market_value"] <= 0 and snap["cash"] <= 0:
        print(f"  ⚠️ 账户 {account_id} 无有效数据，跳过 NAV 写入")
        return None

    prev = prev_nav_row(conn, account_id, trade_date)

    if prev and prev["total"] > 0:
        daily_return = (snap["total"] - prev["total"]) / prev["total"]
        cumulative_return = (snap["total"] / snap["initial"] - 1) if snap["initial"] > 0 else 0.0
        prev_max_dd = prev["max_dd"]
        # 从 peak 算当前回撤（简单：cumulative_return 与 max_drawdown 比较）
        peak_row = conn.execute(
            "SELECT MAX(total_value) FROM sim_daily_nav "
            "WHERE account_id=? AND trade_date<=?",
            (account_id, trade_date),
        ).fetchone()
        peak = peak_row[0] if peak_row and peak_row[0] else snap["initial"]
        if peak > 0:
            drawdown = (snap["total"] - peak) / peak
        else:
            drawdown = 0.0
        max_drawdown = min(prev_max_dd, drawdown) if drawdown < 0 else prev_max_dd
    else:
        # 首次：基准 = initial
        daily_return = 0.0
        cumulative_return = 0.0
        max_drawdown = 0.0

    conn.execute(
        "INSERT INTO sim_daily_nav "
        "(account_id, trade_date, total_value, cash, market_value, "
        "daily_return, cumulative_return, max_drawdown, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP) "
        "ON CONFLICT(account_id, trade_date) DO UPDATE SET "
        "total_value=excluded.total_value, "
        "cash=excluded.cash, "
        "market_value=excluded.market_value, "
        "daily_return=excluded.daily_return, "
        "cumulative_return=excluded.cumulative_return, "
        "max_drawdown=excluded.max_drawdown, "
        "created_at=CURRENT_TIMESTAMP",
        (
            account_id, trade_date,
            round(snap["total"], 2),
            round(snap["cash"], 2),
            round(snap["market_value"], 2),
            round(daily_return, 8),
            round(cumulative_return, 8),
            round(max_drawdown, 8),
        ),
    )
    snap["daily_return"] = daily_return
    snap["cumulative_return"] = cumulative_return
    snap["max_drawdown"] = max_drawdown
    # REQ-069: 同步矫正 sim_account.total_value（防买入时误扣 total 导致盘中口径塌）
    conn.execute(
        "UPDATE sim_account SET total_value=? WHERE id=?",
        (round(snap["total"], 2), account_id),
    )
    print(f"  ✅ 账户 {account_id} NAV 已回写: total=¥{snap['total']:,.2f} "
          f"cash=¥{snap['cash']:,.2f} mv=¥{snap['market_value']:,.2f} "
          f"daily_ret={daily_return*100:+.3f}%")
    return snap


def write_all_navs(trade_date: str, db_path: Path | None = None) -> dict[int, dict]:
    """
    为所有日常账户写入 NAV（acc1 + acc3）。
    返回 {account_id: snapshot}。
    """
    db = db_path or DB_PATH
    conn = sqlite3.connect(str(db))
    results = {}
    try:
        for a in ACCOUNTS:
            snap = write_account_nav(conn, a["id"], trade_date)
            if snap:
                results[a["id"]] = snap
        conn.commit()
    finally:
        conn.close()
    return results


# ── 建仓归因 ──────────────────────────────────────────────────────────────

def get_today_build_positions(conn: sqlite3.Connection, account_id: int, trade_date: str) -> list[dict]:
    """
    REQ-071: 识别今日新建仓的股票。
    条件是：sim_trades 中今日有新买入，且 sim_positions 中该股票今日之前无持仓记录（或 avg_cost ≈ 今日买入价）。
    更准确的方式：检查 sim_positions 是否在 trade_date 当天首次出现。
    返回列表字典，含 stock_code, stock_name, quantity, build_cost, current_price, current_pnl。
    """
    # 今日买入的股票列表（去重）
    codes = set()
    for row in conn.execute(
        "SELECT DISTINCT stock_code FROM sim_trades "
        "WHERE account_id=? AND trade_date=? AND direction='BUY'",
        (account_id, trade_date),
    ):
        codes.add(row[0])

    if not codes:
        return []

    # 检查这些股票此前是否有持仓（在 sim_positions 中 quantity>0）
    # 如果在 trade_date 之前的 sim_trades 中从未出现过，算「新建仓」
    build_positions = []
    for code in codes:
        # 检查该股票此前是否有过交易（任何时候）
        prior = conn.execute(
            "SELECT COUNT(*) FROM sim_trades "
            "WHERE account_id=? AND stock_code=? AND trade_date<?",
            (account_id, code, trade_date),
        ).fetchone()[0]

        # 获取当前持仓
        pos = conn.execute(
            "SELECT stock_code, stock_name, quantity, avg_cost, current_price, "
            "market_value, pnl, pnl_pct "
            "FROM sim_positions WHERE account_id=? AND stock_code=? AND quantity>0",
            (account_id, code),
        ).fetchone()
        if not pos:
            continue

        info = dict(zip(
            ("stock_code", "stock_name", "quantity", "avg_cost",
             "current_price", "market_value", "pnl", "pnl_pct"),
            pos,
        ))

        if prior == 0:
            info["kind"] = "新建仓"
        else:
            # 之前有交易但现持仓 — 可能是加仓
            # 检查是否之前有持仓：前日 quantity
            info["kind"] = "加仓"

        build_positions.append(info)

    return build_positions


def account_block(
    conn: sqlite3.Connection, account_id: int, label: str, trade_date: str
) -> dict:
    acct = conn.execute(
        "SELECT cash, total_value, initial_cash, account_name FROM sim_account WHERE id=?",
        (account_id,),
    ).fetchone()
    if not acct:
        return {
            "id": account_id,
            "label": label,
            "exists": False,
            "cash": 0.0,
            "total": 0.0,
            "initial": 0.0,
            "day_pnl": None,
            "day_pct": None,
            "cum_pnl": None,
            "cum_pct": None,
            "baseline_kind": "missing",
            "trades": [],
            "positions": [],
            "build_positions": [],
        }

    cash, total, initial, name = acct
    cash, total, initial = _f(cash), _f(total), _f(initial)
    name = name or label

    prev = prev_nav_total(conn, account_id, trade_date)
    if prev is not None and prev > 0:
        day_pnl = total - prev
        day_pct = day_pnl / prev * 100.0
        baseline_kind = "prev_nav"
    else:
        day_pnl = None
        day_pct = None
        baseline_kind = "no_prev_nav"

    cum_pnl = total - initial if initial else None
    cum_pct = (cum_pnl / initial * 100.0) if initial else None

    trades = [
        dict(
            zip(
                ("trade_time", "stock_code", "stock_name", "direction",
                 "price", "quantity", "amount", "signal_reason"),
                row,
            )
        )
        for row in conn.execute(
            "SELECT trade_time, stock_code, stock_name, direction, price, quantity, amount, signal_reason "
            "FROM sim_trades WHERE account_id=? AND trade_date=? ORDER BY trade_time, id",
            (account_id, trade_date),
        ).fetchall()
    ]

    positions = [
        dict(
            zip(
                ("stock_code", "stock_name", "quantity", "avg_cost",
                 "current_price", "market_value", "pnl", "pnl_pct"),
                row,
            )
        )
        for row in conn.execute(
            "SELECT stock_code, stock_name, quantity, avg_cost, current_price, market_value, pnl, pnl_pct "
            "FROM sim_positions WHERE account_id=? AND quantity>0 ORDER BY market_value DESC",
            (account_id,),
        ).fetchall()
    ]

    # REQ-071: 建仓归因
    build_positions = get_today_build_positions(conn, account_id, trade_date)

    return {
        "id": account_id,
        "label": f"{label}（{name}）" if name and name != label else label,
        "exists": True,
        "cash": cash,
        "total": total,
        "initial": initial,
        "day_pnl": day_pnl,
        "day_pct": day_pct,
        "cum_pnl": cum_pnl,
        "cum_pct": cum_pct,
        "baseline_kind": baseline_kind,
        "trades": trades,
        "positions": positions,
        "build_positions": build_positions,
    }


def load_swing_snippet(trade_date: str, max_chars: int = 600) -> str | None:
    path = OUTPUT_DIR / "swing_daily" / f"{trade_date}.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    # 日报前面已有波段盈亏，只取真正的挂单明细，避免重复结论和空标题。
    keep: list[str] = []
    in_advice = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## 给你挂单建议"):
            in_advice = True
            continue
        if in_advice and stripped.startswith("## "):
            break
        if in_advice and stripped.startswith(("-", ">")):
            keep.append(line)
        if len(keep) >= 3:
            break
    if not keep:
        return "今日无挂单建议"
    snippet = "\n".join(keep)
    return snippet[:max_chars]


def render_account_md(block: dict) -> list[str]:
    lines = [f"**#{block['id']} {block['label']}**"]
    if not block["exists"]:
        lines.append("- （账户不存在，波段仓请先跑 swing_daily_report）")
        lines.append("")
        return lines

    if block["day_pnl"] is not None:
        day_emoji = "🟢" if block["day_pnl"] > 0 else "🔴" if block["day_pnl"] < 0 else "⚪"
        cumulative = ""
        if block["cum_pnl"] is not None:
            cumulative = (
                f"｜累计 {block['cum_pnl']:+,.2f}（{block['cum_pct']:+.2f}%）"
            )
        lines.append(
            f"- {day_emoji} **今日 {block['day_pnl']:+,.2f}（{block['day_pct']:+.2f}%）**"
            f"｜总资产 {block['total']:,.2f}（较昨日 {block['day_pnl']:+,.2f}）"
            f"{cumulative}"
        )
    else:
        lines.append(
            f"- ⚪ **今日 —（缺昨日净值）**｜总资产 {block['total']:,.2f}"
            f"｜累计 {block['cum_pnl']:+,.2f}（{block['cum_pct']:+.2f}%）"
        )

    trades = block["trades"]
    if trades:
        trade_parts = []
        for t in trades:
            is_buy = str(t["direction"]).upper() == "BUY"
            trade_parts.append(
                f"{'买' if is_buy else '卖'} {t['stock_name']} "
                f"{int(_f(t['quantity']))}股@{_f(t['price']):.2f}"
            )
        lines.append(f"- 成交 {len(trades)}笔：" + "；".join(trade_parts))
    else:
        lines.append("- 成交：无")

    positions = block["positions"]
    if positions:
        position_parts = []
        for p in positions:
            pnl_val = _f(p["pnl"])
            position_parts.append(
                f"{p['stock_name']} {pnl_val:+,.0f}（{_f(p['pnl_pct']):+.2f}%）"
            )
        lines.append(f"- 持仓 {len(positions)}只：" + "；".join(position_parts))
        lines.append("")
    else:
        lines.append("- 持仓：空仓")
        lines.append("")

    return lines


def build_report(trade_date: str | None = None, db_path: Path | None = None) -> str:
    trade_date = trade_date or date.today().isoformat()
    db = db_path or DB_PATH
    conn = sqlite3.connect(str(db))
    try:
        blocks = [
            account_block(conn, a["id"], a["label"], trade_date) for a in ACCOUNTS
        ]
    finally:
        conn.close()

    lines = [
        f"📊 **量化收盘简报 — {trade_date}**",
        "",
    ]
    for b in blocks:
        lines.extend(render_account_md(b))

    swing_block = next((b for b in blocks if b["id"] == 3 and b["exists"]), None)
    if (
        swing_block
        and swing_block["day_pnl"] is not None
        and swing_block["cum_pnl"] is not None
        and swing_block["day_pnl"] * swing_block["cum_pnl"] < 0
    ):
        day_word = "赚" if swing_block["day_pnl"] > 0 else "亏"
        cum_word = "赚" if swing_block["cum_pnl"] > 0 else "亏"
        lines.append(
            f"> ⚠️ **别混淆：波段今天{day_word} "
            f"¥{abs(swing_block['day_pnl']):,.2f}；累计仍{cum_word} "
            f"¥{abs(swing_block['cum_pnl']):,.2f}。**"
        )
        lines.append("")

    swing = load_swing_snippet(trade_date)
    lines.append("**波段操作**")
    if swing:
        lines.append(swing)
    else:
        lines.append(
            f"- ⚠️ 未找到 `{OUTPUT_DIR / 'swing_daily' / (trade_date + '.md')}`。"
            "若现在还没到 16:05，属正常；到点后应有 SwingDaily。"
            "一直没有 → 检查本机 cron / 产机 schtasks。"
        )
    lines.append("")
    lines.append("_今日=相对昨日净值；累计=相对期初资金。_")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--no-nav", action="store_true",
                    help="跳过 NAV 回写（仅生成报告）")
    ap.add_argument("--nav-only", action="store_true",
                    help="仅回写 NAV，不生成报告")
    args = ap.parse_args(argv)

    trade_date = args.date or date.today().isoformat()
    db_path = Path(args.db) if args.db else None

    # REQ-069/REQ-071: 先回写 NAV，再生成报告
    if not args.no_nav:
        print(f"📝 回写 {trade_date} NAV 数据...")
        write_all_navs(trade_date, db_path=db_path)

    # REQ-058: 收盘巡检清仓后悬挂的 threshold_state（全账户）
    try:
        from scripts.patrol_orphan_thresholds import patrol as patrol_orphan_thresholds
        n = patrol_orphan_thresholds(db_path)
        print(f"🧹 REQ-058 orphan threshold patrol: {n}")
    except Exception as e:
        print(f"⚠️ REQ-058 patrol skipped: {e}")

    if args.nav_only:
        print("✅ NAV 回写完成（--nav-only）")
        return 0

    report = build_report(trade_date=trade_date, db_path=db_path)
    print(report)
    out = OUTPUT_DIR / f"daily_close_{trade_date}.md"
    OUTPUT_DIR.mkdir(exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"[saved] {out}")

    if args.no_push:
        return 0
    push_webhook(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
