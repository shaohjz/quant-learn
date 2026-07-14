"""scripts/trade_journal.py — 每日交易台账（给复盘用）

从 sim_live_mirror.db 汇总当日：成交明细、持仓、净值变动。
脚本记事实；OpenClaw 只在文末「复盘备注」补观点，不改数字。

落盘：
  pm/trade_journal/YYYY-MM-DD.md
  pm/trade_journal/YYYY-MM-DD.json
  output/trade_journal/YYYY-MM-DD.md  （镜像，方便日志/排查）

用法：
  python scripts/trade_journal.py
  python scripts/trade_journal.py --date 2026-07-14
  python scripts/trade_journal.py --no-push
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("trade_journal")

DB_PATH = ROOT / "data" / "sim_live_mirror.db"
PM_OUT = ROOT / "pm" / "trade_journal"
OUT_MIRROR = ROOT / "output" / "trade_journal"

ACCOUNT_LABELS = {
    1: "learn",
    2: "real_portfolio",
    3: "swing_trade",
}


def _conn(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    c = sqlite3.connect(str(path))
    c.row_factory = sqlite3.Row
    return c


def _account_label(row: dict) -> str:
    name = (row.get("account_name") or "").strip()
    if name:
        return name
    return ACCOUNT_LABELS.get(int(row["id"]), f"account_{row['id']}")


def _safe_float(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def collect_journal(
    conn: sqlite3.Connection, trade_date: str, db_path: Path | None = None
) -> dict:
    """从 DB 拉某一日台账；无表/无数据时尽量给空结构，不崩。"""
    accounts: list[dict] = []
    try:
        accounts = [dict(r) for r in conn.execute("SELECT * FROM sim_account ORDER BY id").fetchall()]
    except sqlite3.Error as e:
        log.warning("读 sim_account 失败: %s", e)

    trades: list[dict] = []
    try:
        trades = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM sim_trades WHERE trade_date=? "
                "ORDER BY account_id, COALESCE(trade_time,''), id",
                (trade_date,),
            ).fetchall()
        ]
    except sqlite3.Error as e:
        log.warning("读 sim_trades 失败: %s", e)

    positions: list[dict] = []
    try:
        positions = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM sim_positions WHERE quantity>0 ORDER BY account_id, stock_code"
            ).fetchall()
        ]
    except sqlite3.Error as e:
        log.warning("读 sim_positions 失败: %s", e)

    nav_today: list[dict] = []
    nav_prev: dict[int, dict] = {}
    try:
        nav_today = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM sim_daily_nav WHERE trade_date=? ORDER BY account_id",
                (trade_date,),
            ).fetchall()
        ]
        for acc in accounts:
            aid = int(acc["id"])
            prev = conn.execute(
                "SELECT * FROM sim_daily_nav WHERE account_id=? AND trade_date<? "
                "ORDER BY trade_date DESC LIMIT 1",
                (aid, trade_date),
            ).fetchone()
            if prev:
                nav_prev[aid] = dict(prev)
    except sqlite3.Error as e:
        log.warning("读 sim_daily_nav 失败: %s", e)

    by_account: list[dict] = []
    for acc in accounts:
        aid = int(acc["id"])
        label = _account_label(acc)
        acc_trades = [t for t in trades if int(t.get("account_id") or 0) == aid]
        acc_pos = [p for p in positions if int(p.get("account_id") or 0) == aid]
        today_nav = next((n for n in nav_today if int(n.get("account_id") or 0) == aid), None)
        prev = nav_prev.get(aid)

        total_now = _safe_float(
            (today_nav or {}).get("total_value", acc.get("total_value"))
        )
        total_prev = _safe_float((prev or {}).get("total_value"), total_now)
        day_pnl = total_now - total_prev if prev else None
        day_pct = (day_pnl / total_prev * 100.0) if prev and total_prev else None

        buy_amt = sum(
            _safe_float(t.get("amount"))
            for t in acc_trades
            if str(t.get("direction") or "").upper() in ("BUY", "B", "买")
        )
        sell_amt = sum(
            _safe_float(t.get("amount"))
            for t in acc_trades
            if str(t.get("direction") or "").upper() in ("SELL", "S", "卖")
        )
        commission = sum(_safe_float(t.get("commission")) for t in acc_trades)

        by_account.append(
            {
                "account_id": aid,
                "label": label,
                "cash": _safe_float(acc.get("cash")),
                "total_value": total_now,
                "day_pnl": day_pnl,
                "day_pct": day_pct,
                "buy_amount": buy_amt,
                "sell_amount": sell_amt,
                "commission": commission,
                "trade_count": len(acc_trades),
                "trades": [_normalize_trade(t) for t in acc_trades],
                "positions": [_normalize_pos(p) for p in acc_pos],
                "nav_today": dict(today_nav) if today_nav else None,
            }
        )

    return {
        "trade_date": trade_date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db_path": str(db_path or DB_PATH),
        "totals": {
            "accounts": len(by_account),
            "trades": len(trades),
            "open_positions": len(positions),
        },
        "accounts": by_account,
    }


def _normalize_trade(t: dict) -> dict:
    return {
        "id": t.get("id"),
        "account_id": t.get("account_id"),
        "trade_time": t.get("trade_time") or "",
        "stock_code": t.get("stock_code") or "",
        "stock_name": t.get("stock_name") or "",
        "direction": t.get("direction") or "",
        "price": _safe_float(t.get("price")),
        "quantity": int(_safe_float(t.get("quantity"))),
        "amount": _safe_float(t.get("amount")),
        "commission": _safe_float(t.get("commission")),
        "signal_reason": (t.get("signal_reason") or "")[:200],
    }


def _normalize_pos(p: dict) -> dict:
    qty = int(_safe_float(p.get("quantity")))
    cost = _safe_float(p.get("avg_cost"))
    price = _safe_float(p.get("current_price"))
    pnl = _safe_float(p.get("pnl"), (price - cost) * qty if qty else 0.0)
    pnl_pct = _safe_float(
        p.get("pnl_pct"),
        ((price - cost) / cost * 100.0) if cost else 0.0,
    )
    return {
        "account_id": p.get("account_id"),
        "stock_code": p.get("stock_code") or "",
        "stock_name": p.get("stock_name") or "",
        "quantity": qty,
        "avg_cost": cost,
        "current_price": price,
        "market_value": _safe_float(p.get("market_value"), price * qty),
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "trailing_stop_price": p.get("trailing_stop_price"),
    }


def render_markdown(journal: dict) -> str:
    d = journal["trade_date"]
    lines = [
        f"# 交易台账 {d}",
        "",
        f"> 脚本自动生成于 `{journal['generated_at']}`。数字以 DB 为准；OpenClaw 只填文末「复盘备注」。",
        "",
        "## 总览",
        "",
        f"- 账户数：{journal['totals']['accounts']}",
        f"- 当日成交笔数：{journal['totals']['trades']}",
        f"- 当前持仓条数：{journal['totals']['open_positions']}",
        "",
    ]

    if not journal["accounts"]:
        lines += ["（无账户数据）", ""]
    else:
        lines += [
            "| 账户 | 现金 | 总资产 | 日盈亏 | 日涨跌% | 买额 | 卖额 | 成交笔数 |",
            "|------|-----:|-------:|-------:|--------:|-----:|-----:|---------:|",
        ]
        for a in journal["accounts"]:
            dp = "—" if a["day_pnl"] is None else f"{a['day_pnl']:.2f}"
            pct = "—" if a["day_pct"] is None else f"{a['day_pct']:.2f}"
            lines.append(
                f"| #{a['account_id']} {a['label']} | {a['cash']:.2f} | {a['total_value']:.2f} | "
                f"{dp} | {pct} | {a['buy_amount']:.2f} | {a['sell_amount']:.2f} | {a['trade_count']} |"
            )
        lines.append("")

    for a in journal["accounts"]:
        lines += [
            f"## #{a['account_id']} {a['label']}",
            "",
            "### 当日成交",
            "",
        ]
        if not a["trades"]:
            lines += ["（无成交）", ""]
        else:
            lines += [
                "| 时间 | 方向 | 代码 | 名称 | 数量 | 价格 | 金额 | 佣金 | 原因 |",
                "|------|------|------|------|-----:|-----:|-----:|-----:|------|",
            ]
            for t in a["trades"]:
                lines.append(
                    f"| {t['trade_time'] or '-'} | {t['direction']} | {t['stock_code']} | "
                    f"{t['stock_name']} | {t['quantity']} | {t['price']:.2f} | {t['amount']:.2f} | "
                    f"{t['commission']:.2f} | {t['signal_reason'] or '-'} |"
                )
            lines.append("")

        lines += ["### 当前持仓", ""]
        if not a["positions"]:
            lines += ["（空仓）", ""]
        else:
            lines += [
                "| 代码 | 名称 | 数量 | 成本 | 现价 | 市值 | 浮盈 | 浮盈% | 止损 |",
                "|------|------|-----:|-----:|-----:|-----:|-----:|------:|------|",
            ]
            for p in a["positions"]:
                stop = p.get("trailing_stop_price")
                stop_s = f"{float(stop):.2f}" if stop not in (None, "") else "-"
                lines.append(
                    f"| {p['stock_code']} | {p['stock_name']} | {p['quantity']} | "
                    f"{p['avg_cost']:.2f} | {p['current_price']:.2f} | {p['market_value']:.2f} | "
                    f"{p['pnl']:.2f} | {p['pnl_pct']:.2f} | {stop_s} |"
                )
            lines.append("")

    lines += [
        "## 复盘备注（OpenClaw / 人工填写）",
        "",
        "- 今日做对了什么：",
        "- 今日做错了什么：",
        "- 明日挂单 / 关注：",
        "- 是否开 REQ/BUG（编号）：",
        "",
    ]
    return "\n".join(lines)


def write_journal(journal: dict, md: str) -> tuple[Path, Path, Path]:
    PM_OUT.mkdir(parents=True, exist_ok=True)
    OUT_MIRROR.mkdir(parents=True, exist_ok=True)
    d = journal["trade_date"]
    md_path = PM_OUT / f"{d}.md"
    json_path = PM_OUT / f"{d}.json"
    mirror = OUT_MIRROR / f"{d}.md"

    # 保留已有「复盘备注」手写内容（若存在）
    md_to_write = md
    if md_path.exists():
        old = md_path.read_text(encoding="utf-8")
        marker = "## 复盘备注"
        if marker in old:
            old_notes = old.split(marker, 1)[1]
            # 若旧备注不只是模板空行，接到新稿末尾覆盖模板区
            if any(
                line.strip() and not line.strip().startswith("- 今日") and not line.strip().startswith("- 是否")
                for line in old_notes.splitlines()
                if line.strip() and not line.strip().startswith("-")
            ) or _notes_filled(old_notes):
                base = md.split(marker, 1)[0]
                md_to_write = base + marker + old_notes

    md_path.write_text(md_to_write, encoding="utf-8")
    json_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    mirror.write_text(md_to_write, encoding="utf-8")
    return md_path, json_path, mirror


def _notes_filled(notes_block: str) -> bool:
    """模板默认四行「- 今日…：」后面若已有非空内容则视为已填写。"""
    for line in notes_block.splitlines():
        s = line.strip()
        if not s.startswith("-"):
            continue
        if "：" in s:
            after = s.split("：", 1)[1].strip()
            if after:
                return True
        elif ":" in s:
            after = s.split(":", 1)[1].strip()
            if after:
                return True
    return False


def maybe_push_wecom(md_path: Path, journal: dict, dry_run: bool = False) -> None:
    """短摘要推企微；失败只打日志。"""
    if dry_run:
        log.info("跳过推送 (--no-push)")
        return
    total_trades = journal["totals"]["trades"]
    bits = [f"📒 交易台账 {journal['trade_date']}", f"成交 {total_trades} 笔"]
    for a in journal["accounts"]:
        if a["trade_count"] or a["day_pnl"] is not None:
            pnl = "—" if a["day_pnl"] is None else f"{a['day_pnl']:+.0f}"
            bits.append(f"#{a['account_id']}{a['label']}: {a['trade_count']}笔 日盈亏{pnl}")
    bits.append(f"详情: pm/trade_journal/{journal['trade_date']}.md")
    text = "\n".join(bits)

    try:
        from vqlearn.notify.wecom import send_markdown  # type: ignore
        send_markdown(text)
        log.info("企微已推送摘要")
        return
    except Exception:
        pass
    try:
        import os
        import urllib.request

        key = os.environ.get("WECOM_WEBHOOK_KEY") or os.environ.get("WECOM_BOT_KEY")
        if not key:
            # 尝试 config
            cfg = ROOT / "config.local.yaml"
            if cfg.exists():
                import re
                m = re.search(r"webhook[^\n]*key[\"']?\s*[:=]\s*[\"']?([a-zA-Z0-9\-]+)", cfg.read_text(encoding="utf-8", errors="ignore"))
                if m:
                    key = m.group(1)
        if not key:
            log.info("无 webhook，跳过推送（文件已写）")
            return
        url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
        body = json.dumps({"msgtype": "markdown", "markdown": {"content": text}}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)
        log.info("企微 webhook 推送完成")
    except Exception as e:
        log.warning("企微推送失败（台账已落盘）: %s", e)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="每日交易台账")
    ap.add_argument("--date", default=None, help="交易日 YYYY-MM-DD，默认今天")
    ap.add_argument("--db", default=None, help="数据库路径（测试用）")
    ap.add_argument("--no-push", action="store_true", help="不推企微")
    args = ap.parse_args(argv)

    trade_date = args.date or date.today().isoformat()
    db_path = Path(args.db) if args.db else DB_PATH
    if not db_path.exists():
        log.error("数据库不存在: %s", db_path)
        return 1

    conn = _conn(db_path)
    try:
        journal = collect_journal(conn, trade_date, db_path=db_path)
    finally:
        conn.close()

    md = render_markdown(journal)
    md_path, json_path, mirror = write_journal(journal, md)
    log.info("已写 %s", md_path)
    log.info("已写 %s", json_path)
    log.info("镜像 %s", mirror)

    maybe_push_wecom(md_path, journal, dry_run=args.no_push)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
