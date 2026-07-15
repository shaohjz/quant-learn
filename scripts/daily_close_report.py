"""scripts/daily_close_report.py — 收盘交易日报（双账户）

推送 #1 模拟学习仓 + #3 波段仓。当日盈亏 = 今日总值 − 昨日 NAV（禁止再写死 10 万基准）。

用法：
  python scripts/daily_close_report.py
  python scripts/daily_close_report.py --no-push
  python scripts/daily_close_report.py --date 2026-07-15 --no-push
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUTPUT_DIR = ROOT / "output"
DB_PATH = ROOT / "data" / "sim_live_mirror.db"

# 主人约定：日常只看这两个
ACCOUNTS = (
    {"id": 1, "label": "模拟学习仓", "short": "学习"},
    {"id": 3, "label": "波段模拟仓", "short": "波段"},
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


def account_block(conn: sqlite3.Connection, account_id: int, label: str, trade_date: str) -> dict:
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
        # 无昨日净值：不当「日盈亏」，标成相对期初（避免再骗主人）
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
    }


def load_swing_snippet(trade_date: str, max_chars: int = 600) -> str | None:
    path = ROOT / "output" / "swing_daily" / f"{trade_date}.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    # 取结论几行
    keep = []
    for line in text.splitlines():
        if any(k in line for k in ("波段结论", "赚", "亏", "挂单建议", "今日", "建议")):
            keep.append(line)
        if len(keep) >= 12:
            break
    if not keep:
        keep = text.splitlines()[:8]
    snippet = "\n".join(keep)
    return snippet[:max_chars]


def render_account_md(block: dict) -> list[str]:
    lines = [f"**{block['label']}** `#{block['id']}`"]
    if not block["exists"]:
        lines.append("- （账户不存在，波段仓请先跑 swing_daily_report）")
        lines.append("")
        return lines

    lines.append(f"- 总资产：¥{block['total']:,.2f}")
    lines.append(f"- 可用现金：¥{block['cash']:,.2f}")

    if block["day_pnl"] is not None:
        lines.append(
            f"- 当日盈亏：¥{block['day_pnl']:+,.2f}（{block['day_pct']:+.2f}%）← 相对昨日净值"
        )
    else:
        lines.append("- 当日盈亏：—（无昨日净值，无法算日收益）")

    if block["cum_pnl"] is not None:
        lines.append(
            f"- 累计盈亏：¥{block['cum_pnl']:+,.2f}（{block['cum_pct']:+.2f}%）← 相对期初 ¥{block['initial']:,.0f}"
        )
    lines.append("")

    trades = block["trades"]
    if trades:
        lines.append(f"**今日交易（{len(trades)}笔）**")
        for t in trades:
            emoji = "🟢" if str(t["direction"]).upper() == "BUY" else "🔴"
            lines.append(
                f"- {emoji} {t['trade_time'] or '-'} {t['stock_name']}（{t['stock_code']}）"
                f"{t['direction']} {int(_f(t['quantity']))}股 @ ¥{_f(t['price']):.2f}，"
                f"金额¥{_f(t['amount']):.0f}"
            )
            if t.get("signal_reason"):
                lines.append(f"  └ 原因：{t['signal_reason']}")
        lines.append("")
    else:
        lines.append("**今日交易：无**")
        lines.append("")

    positions = block["positions"]
    if positions:
        lines.append(f"**当前持仓（{len(positions)}只）**")
        for p in positions:
            pnl_val = _f(p["pnl"])
            emoji = "🟢" if pnl_val >= 0 else "🔴"
            lines.append(
                f"- {emoji} {p['stock_name']}（{p['stock_code']}）：{int(_f(p['quantity']))}股，"
                f"成本¥{_f(p['avg_cost']):.2f}，现价¥{_f(p['current_price']):.2f}，"
                f"盈亏{pnl_val:+,.2f}（{_f(p['pnl_pct']):+.2f}%）"
            )
        lines.append("")
    else:
        lines.append("**当前持仓：空仓**")
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
        f"📊 **量化交易日报 — {trade_date}**",
        "",
        "> 账户约定：**#1 模拟学习** + **#3 波段**（#2 真仓镜像可选，默认不推）",
        "",
    ]
    for b in blocks:
        lines.extend(render_account_md(b))

    swing = load_swing_snippet(trade_date)
    lines.append("**波段结论 / 挂单建议**")
    if swing:
        lines.append(swing)
    else:
        lines.append(
            "- ⚠️ 未找到 `output/swing_daily/" + trade_date + ".md`。"
            "若现在还没到 16:05，属正常；到点后应有 `QuantLearn_SwingDaily` 推送。"
            "一直没有 → 检查 schtasks / `git pull` 是否部署。"
        )
    lines.append("")
    lines.append("_本报告由量化系统自动生成（当日盈亏=相对昨日净值）_")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args(argv)

    report = build_report(
        trade_date=args.date,
        db_path=Path(args.db) if args.db else None,
    )
    print(report)
    out = OUTPUT_DIR / f"daily_close_{args.date or date.today().isoformat()}.md"
    OUTPUT_DIR.mkdir(exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"[saved] {out}")

    if args.no_push:
        return 0
    push_webhook(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
