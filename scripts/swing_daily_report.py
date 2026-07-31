"""scripts/swing_daily_report.py — 波段模拟盘日报（给你自己挂单用）

目标：你每天只看短结论 —— 波段今天赚还是亏、该挂什么价。

流程：
  1. 扫描动态稳定池 → 写 swing_scan_results
  2. 合并盘中盯盘已提醒但未成交的 BUY（补漏）
  3. 在账户 #3 (swing_trade) 上模拟买卖（止损/止盈/新建）
  4. 记净值 → 算今日盈亏 / 累计盈亏
  5. 推一条短结论 + 给你真实账户的挂单建议

说明：盘中 Pulse→swing_intraday_watch 已会同步模拟买入；本脚本收盘再扫 + 补漏。

用法：
  python scripts/swing_daily_report.py
  python scripts/swing_daily_report.py --no-trade   # 只扫描+建议，不模拟成交
  python scripts/swing_daily_report.py --no-push
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from swing_auto import (  # noqa: E402
    STAMP_TAX_RATE,
    COMMISSION_RATE,
    MIN_COMMISSION,
    get_stock_pool,
    scan_stock,
    save_results,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("swing_daily")

from sim.config_resolver import resolve_artifact_root, resolve_db_path  # noqa: E402

DB_PATH = resolve_db_path()
OUT_DIR = resolve_artifact_root() / "swing_daily"
SWING_ACCOUNT_ID = 3
SWING_ACCOUNT_NAME = "swing_trade"
# 资金真源：config.yaml accounts.swing.initial_cash（缺失时兜底 5 万）
try:
    from sim.config import account_initial_cash as _account_initial_cash
    SWING_INITIAL_CASH = _account_initial_cash(SWING_ACCOUNT_ID)
except Exception:
    SWING_INITIAL_CASH = 50_000.0
STOP_LOSS_PCT = 0.05
TAKE_PROFIT_PCT = 0.08
MAX_POSITIONS = 3
MIN_SCORE_BUY = 5
EXECUTABLE_TYPES = {"A", "B"}
SINGLE_BUDGET = 10_000.0
LOT = 100


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def ensure_swing_account() -> dict:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM sim_account WHERE id=?", (SWING_ACCOUNT_ID,)).fetchone()
        if row:
            return dict(row)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sim_account)").fetchall()}
        if "account_name" in cols and "initial_cash" in cols:
            conn.execute(
                "INSERT INTO sim_account (id, account_name, initial_cash, cash, total_value) "
                "VALUES (?, ?, ?, ?, ?)",
                (SWING_ACCOUNT_ID, SWING_ACCOUNT_NAME, SWING_INITIAL_CASH,
                 SWING_INITIAL_CASH, SWING_INITIAL_CASH),
            )
        else:
            conn.execute(
                "INSERT INTO sim_account (id, cash, total_value) VALUES (?, ?, ?)",
                (SWING_ACCOUNT_ID, SWING_INITIAL_CASH, SWING_INITIAL_CASH),
            )
        conn.commit()
        log.info("创建波段账户 #%s 初始 %.0f", SWING_ACCOUNT_ID, SWING_INITIAL_CASH)
        return dict(conn.execute("SELECT * FROM sim_account WHERE id=?", (SWING_ACCOUNT_ID,)).fetchone())
    finally:
        conn.close()


def get_quote_6(code6: str) -> dict | None:
    prefix = "sh" if code6.startswith(("5", "6", "9")) else "sz"
    url = f"https://qt.gtimg.cn/q={prefix}{code6}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        vals = resp.read().decode("gbk").split('"')[1].split("~")
        return {
            "name": vals[1],
            "price": float(vals[3]) if vals[3] else 0,
            "change_pct": float(vals[32]) if vals[32] else 0,
            "full": f"{prefix}{code6}",
        }
    except Exception as e:
        log.warning("行情失败 %s: %s", code6, e)
        return None


def _fee_buy(amount: float) -> float:
    return max(amount * COMMISSION_RATE, MIN_COMMISSION)


def _fee_sell(amount: float) -> tuple[float, float]:
    return max(amount * COMMISSION_RATE, MIN_COMMISSION), amount * STAMP_TAX_RATE


def load_positions() -> list[dict]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM sim_positions WHERE account_id=? AND quantity>0",
            (SWING_ACCOUNT_ID,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def sim_sell(pos: dict, price: float, reason: str) -> dict:
    code = str(pos["stock_code"]).zfill(6)[-6:]
    name = pos.get("stock_name") or code
    qty = int(pos["quantity"])
    amount = price * qty
    commission, stamp = _fee_sell(amount)
    net = amount - commission - stamp
    cost = float(pos.get("avg_cost") or 0)
    realized = (price - cost) * qty - commission - stamp
    conn = _conn()
    try:
        conn.execute("BEGIN")
        conn.execute(
            "UPDATE sim_account SET cash=cash+?, total_value=total_value+? WHERE id=?",
            (net, net - float(pos.get("market_value") or amount), SWING_ACCOUNT_ID),
        )
        # 更稳：卖后重算 total 由 snapshot 覆盖
        conn.execute(
            "UPDATE sim_positions SET quantity=0, current_price=?, market_value=0, pnl=0, pnl_pct=0 "
            "WHERE account_id=? AND stock_code=? AND quantity>0",
            (price, SWING_ACCOUNT_ID, code),
        )
        today = date.today().isoformat()
        now_t = datetime.now().strftime("%H:%M:%S")
        conn.execute(
            "INSERT INTO sim_trades (account_id, trade_date, trade_time, stock_code, stock_name, "
            "direction, price, quantity, amount, commission, signal_reason) "
            "VALUES (?,?,?,?,?,'SELL',?,?,?,?,?)",
            (SWING_ACCOUNT_ID, today, now_t, code, name, price, qty, net, commission,
             f"波段模拟|{reason}"),
        )
        conn.commit()
        log.info("SELL %s %s股@%.2f 净%.2f 已实现%.2f (%s)", code, qty, price, net, realized, reason)
        return {"ok": True, "code": code, "name": name, "side": "SELL", "qty": qty,
                "price": price, "realized": realized, "reason": reason}
    except Exception as e:
        conn.execute("ROLLBACK")
        log.error("SELL fail %s: %s", code, e)
        return {"ok": False, "code": code, "reason": str(e)}
    finally:
        conn.close()


def sim_buy(code: str, name: str, price: float, reason: str) -> dict:
    code = code.zfill(6)[-6:]
    conn = _conn()
    try:
        conn.execute("BEGIN")
        cash = float(conn.execute(
            "SELECT cash FROM sim_account WHERE id=?", (SWING_ACCOUNT_ID,)
        ).fetchone()[0])
        budget = min(cash * 0.95, SINGLE_BUDGET)
        qty = int(budget / price / LOT) * LOT
        if qty < LOT:
            conn.execute("ROLLBACK")
            return {"ok": False, "code": code, "reason": "预算不够1手"}
        amount = price * qty
        commission = _fee_buy(amount)
        total = amount + commission
        if total > cash:
            conn.execute("ROLLBACK")
            return {"ok": False, "code": code, "reason": f"现金不足 need={total:.0f}"}
        conn.execute(
            "UPDATE sim_account SET cash=cash-? WHERE id=?",
            (total, SWING_ACCOUNT_ID),
        )
        existing = conn.execute(
            "SELECT id, quantity, avg_cost FROM sim_positions "
            "WHERE account_id=? AND stock_code=? AND quantity>0",
            (SWING_ACCOUNT_ID, code),
        ).fetchone()
        if existing:
            nq = existing["quantity"] + qty
            nc = (existing["avg_cost"] * existing["quantity"] + price * qty) / nq
            conn.execute(
                "UPDATE sim_positions SET quantity=?, avg_cost=?, current_price=?, market_value=? "
                "WHERE id=?",
                (nq, nc, price, price * nq, existing["id"]),
            )
        else:
            stop0 = round(price * (1 - STOP_LOSS_PCT), 2)
            try:
                conn.execute(
                    "INSERT INTO sim_positions (account_id, stock_code, stock_name, quantity, avg_cost, "
                    "current_price, market_value, pnl, pnl_pct, highest_price, trailing_stop_price) "
                    "VALUES (?,?,?,?,?,?,?,0,0,?,?)",
                    (SWING_ACCOUNT_ID, code, name, qty, price, price, price * qty, price, stop0),
                )
            except sqlite3.OperationalError:
                conn.execute(
                    "INSERT INTO sim_positions (account_id, stock_code, stock_name, quantity, avg_cost, "
                    "current_price, market_value) VALUES (?,?,?,?,?,?,?)",
                    (SWING_ACCOUNT_ID, code, name, qty, price, price, price * qty),
                )
        today = date.today().isoformat()
        now_t = datetime.now().strftime("%H:%M:%S")
        conn.execute(
            "INSERT INTO sim_trades (account_id, trade_date, trade_time, stock_code, stock_name, "
            "direction, price, quantity, amount, commission, signal_reason) "
            "VALUES (?,?,?,?,?,'BUY',?,?,?,?,?)",
            (SWING_ACCOUNT_ID, today, now_t, code, name, price, qty, total, commission,
             f"波段模拟|{reason}"),
        )
        conn.commit()
        log.info("BUY %s %s股@%.2f 花%.2f (%s)", code, qty, price, total, reason)
        return {"ok": True, "code": code, "name": name, "side": "BUY", "qty": qty,
                "price": price, "cost": total, "reason": reason,
                "stop": round(price * (1 - STOP_LOSS_PCT), 2),
                "target": round(price * (1 + TAKE_PROFIT_PCT), 2)}
    except Exception as e:
        conn.execute("ROLLBACK")
        log.error("BUY fail %s: %s", code, e)
        return {"ok": False, "code": code, "reason": str(e)}
    finally:
        conn.close()


def refresh_and_mark(positions: list[dict]) -> list[dict]:
    out = []
    for p in positions:
        code = str(p["stock_code"]).zfill(6)[-6:]
        q = get_quote_6(code)
        price = float(q["price"]) if q and q["price"] > 0 else float(p.get("current_price") or p.get("avg_cost") or 0)
        cost = float(p.get("avg_cost") or 0)
        qty = int(p.get("quantity") or 0)
        pnl_pct = (price / cost - 1) * 100 if cost else 0
        stop = cost * (1 - STOP_LOSS_PCT) if cost else 0
        target = cost * (1 + TAKE_PROFIT_PCT) if cost else 0
        if price <= stop:
            action, reason = "SELL_STOP", f"止损@{stop:.2f}"
        elif price >= target:
            action, reason = "SELL_TP", f"止盈@{target:.2f}"
        else:
            action, reason = "HOLD", "持有"
        item = {
            **p, "stock_code": code, "current_price": price,
            "market_value": price * qty, "pnl": (price - cost) * qty,
            "pnl_pct": pnl_pct, "stop_price": stop, "target_price": target,
            "action": action, "action_reason": reason,
            "stock_name": p.get("stock_name") or (q["name"] if q else code),
        }
        out.append(item)
        conn = _conn()
        try:
            conn.execute(
                "UPDATE sim_positions SET current_price=?, market_value=?, pnl=?, pnl_pct=? "
                "WHERE account_id=? AND stock_code=? AND quantity>0",
                (price, price * qty, item["pnl"], pnl_pct, SWING_ACCOUNT_ID, code),
            )
            conn.commit()
        finally:
            conn.close()
        time.sleep(0.12)
    return out


def run_scan() -> list[dict]:
    results = []
    for code, name in get_stock_pool():
        try:
            r = scan_stock(code, name)
            if r:
                results.append(r)
        except Exception:
            pass
        time.sleep(0.12)
    results.sort(key=lambda x: x["score"], reverse=True)
    save_results(results, date.today().isoformat())
    return results


def load_scan_results(scan_date: str) -> list[dict]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM swing_scan_results WHERE scan_date=? ORDER BY score DESC",
            (scan_date,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def pick_buys(scan_rows: list[dict], positions: list[dict]) -> list[dict]:
    held = {str(p["stock_code"]).zfill(6)[-6:] for p in positions}
    picks = []
    for r in scan_rows:
        code = str(r.get("code") or r.get("stock_code") or "")
        code6 = code[-6:] if code else ""
        if not code6 or code6 in held:
            continue
        stype = r.get("signal_type") or ""
        score = int(r.get("score") or 0)
        if stype not in EXECUTABLE_TYPES or score < MIN_SCORE_BUY:
            continue
        price = float(r.get("price") or 0)
        support = float(r.get("support") or 0)
        resist = float(r.get("resist") or 0)
        picks.append({
            "code": code6,
            "name": r.get("name") or r.get("stock_name"),
            "price": price,
            "score": score,
            "signal_type": stype,
            "support": support,
            "resist": resist,
            "net_rr": float(r.get("net_rr") or r.get("risk_reward") or 0),
            "stop": round(support * 0.98, 2) if support else round(price * (1 - STOP_LOSS_PCT), 2),
            "target": resist if resist else round(price * (1 + TAKE_PROFIT_PCT), 2),
            "signals": r.get("signals"),
        })
        if len(picks) >= MAX_POSITIONS:
            break
    return picks


def load_intraday_buy_alerts(today: str | None = None) -> list[dict]:
    """读盘中盯盘日志里的 BUY，供收盘补漏（提醒过但未写入持仓）。"""
    day = today or date.today().isoformat()
    path = ROOT / "output" / "swing_intraday" / f"{day}.log"
    if not path.exists():
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        # 格式: ISO BUY:300059 {...}
        parts = line.split(" ", 2)
        if len(parts) < 3:
            continue
        key, raw = parts[1], parts[2]
        if not key.startswith("BUY:"):
            continue
        code = key.split(":", 1)[1].zfill(6)[-6:]
        if code in seen:
            continue
        try:
            a = json.loads(raw)
        except json.JSONDecodeError:
            continue
        # 日志里已记模拟成交成功 → 不进补漏名单
        fill = a.get("sim_fill") or {}
        if fill.get("ok") and fill.get("side") == "BUY":
            seen.add(code)
            continue
        price = float(a.get("price") or 0)
        if price <= 0:
            continue
        support = float(a.get("support") or 0)
        resist = float(a.get("resist") or 0)
        seen.add(code)
        out.append({
            "code": code,
            "name": a.get("name") or code,
            "price": price,
            "score": int(a.get("score") or 0),
            "signal_type": a.get("signal_type") or "A",
            "support": support,
            "resist": resist,
            "net_rr": float(a.get("net_rr") or 0),
            "stop": float(a.get("stop") or round(price * (1 - STOP_LOSS_PCT), 2)),
            "target": float(a.get("target") or round(price * (1 + TAKE_PROFIT_PCT), 2)),
            "signals": a.get("signals"),
            "from_intraday": True,
        })
    return out


def merge_buys(scan_picks: list[dict], intraday: list[dict], positions: list[dict]) -> list[dict]:
    """收盘扫描 + 盘中提醒补漏；盘中提醒优先保留（按提醒价模拟）。"""
    held = {str(p["stock_code"]).zfill(6)[-6:] for p in positions}
    merged: list[dict] = []
    seen: set[str] = set()
    for b in intraday + scan_picks:
        code = str(b["code"]).zfill(6)[-6:]
        if code in held or code in seen:
            continue
        seen.add(code)
        merged.append(b)
        if len(merged) >= MAX_POSITIONS:
            break
    return merged


def today_bought_codes(today: str) -> set[str]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT stock_code FROM sim_trades WHERE account_id=? AND trade_date=? AND direction='BUY'",
            (SWING_ACCOUNT_ID, today),
        ).fetchall()
        return {str(r[0]).zfill(6)[-6:] for r in rows}
    except sqlite3.OperationalError:
        return set()
    finally:
        conn.close()


def execute_sim(marked: list[dict], buys: list[dict]) -> list[dict]:
    """真模拟：先卖后买。返回成交列表。"""
    fills = []
    for p in marked:
        if p["action"].startswith("SELL"):
            fills.append(sim_sell(p, p["current_price"], p["action_reason"]))
    positions = load_positions()
    slots = max(0, MAX_POSITIONS - len(positions))
    for b in buys[:slots]:
        tag = "盘中补漏" if b.get("from_intraday") else "收盘扫描"
        reason = f"{tag}|{b['signal_type']}分{b['score']} rr={b['net_rr']:.2f}"
        fills.append(sim_buy(b["code"], b["name"], b["price"], reason))
    return fills


def snapshot() -> dict:
    acct = ensure_swing_account()
    positions = load_positions()
    # 刷新市值
    mv = 0.0
    pos_out = []
    for p in positions:
        code = str(p["stock_code"]).zfill(6)[-6:]
        q = get_quote_6(code)
        price = float(q["price"]) if q and q["price"] > 0 else float(p.get("current_price") or p.get("avg_cost") or 0)
        cost = float(p.get("avg_cost") or 0)
        qty = int(p["quantity"])
        mv += price * qty
        pos_out.append({
            "code": code,
            "name": p.get("stock_name") or code,
            "qty": qty,
            "cost": cost,
            "price": price,
            "pnl_pct": (price / cost - 1) * 100 if cost else 0,
            "stop": round(cost * (1 - STOP_LOSS_PCT), 2),
            "target": round(cost * (1 + TAKE_PROFIT_PCT), 2),
        })
        time.sleep(0.08)
    cash = float(acct.get("cash") or 0)
    total = cash + mv
    init = float(acct.get("initial_cash") or SWING_INITIAL_CASH)
    # 写回 total_value
    conn = _conn()
    try:
        conn.execute(
            "UPDATE sim_account SET total_value=?, cash=? WHERE id=?",
            (total, cash, SWING_ACCOUNT_ID),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "cash": cash,
        "market_value": mv,
        "total": total,
        "init": init,
        "cum_pnl": total - init,
        "cum_pct": (total / init - 1) * 100 if init else 0,
        "positions": pos_out,
    }


def prev_nav(today: str) -> float | None:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT total_value FROM sim_daily_nav WHERE account_id=? AND trade_date<? "
            "ORDER BY trade_date DESC LIMIT 1",
            (SWING_ACCOUNT_ID, today),
        ).fetchone()
        return float(row[0]) if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def write_nav(today: str, snap: dict) -> None:
    conn = _conn()
    try:
        prev = prev_nav(today)
        daily_ret = ((snap["total"] / prev) - 1) if prev and prev > 0 else 0.0
        cum = snap["cum_pct"] / 100.0
        conn.execute(
            "INSERT INTO sim_daily_nav (account_id, trade_date, total_value, cash, market_value, "
            "daily_return, cumulative_return) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(account_id, trade_date) DO UPDATE SET "
            "total_value=excluded.total_value, cash=excluded.cash, "
            "market_value=excluded.market_value, daily_return=excluded.daily_return, "
            "cumulative_return=excluded.cumulative_return",
            (SWING_ACCOUNT_ID, today, snap["total"], snap["cash"], snap["market_value"],
             daily_ret, cum),
        )
        conn.commit()
    finally:
        conn.close()


def today_realized(today: str) -> float:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT direction, price, quantity, commission, signal_reason FROM sim_trades "
            "WHERE account_id=? AND trade_date=?",
            (SWING_ACCOUNT_ID, today),
        ).fetchall()
        # 简化：只累计 SELL 已实现（BUY 不算实现盈亏）
        # 已实现在 fills 里更准，这里作备用
        return 0.0
    finally:
        conn.close()


def build_conclusion(
    today: str,
    snap: dict,
    fills: list[dict],
    buys_plan: list[dict],
    day_pnl: float,
    day_pct: float,
) -> dict:
    sold = [f for f in fills if f.get("ok") and f.get("side") == "SELL"]
    bought = [f for f in fills if f.get("ok") and f.get("side") == "BUY"]
    realized = sum(float(f.get("realized") or 0) for f in sold)

    if day_pnl > 5:
        verdict = f"波段模拟今日赚 ¥{day_pnl:.0f}（{day_pct:+.2f}%）"
    elif day_pnl < -5:
        verdict = f"波段模拟今日亏 ¥{abs(day_pnl):.0f}（{day_pct:+.2f}%）"
    else:
        verdict = f"波段模拟今日基本平（¥{day_pnl:+.0f} / {day_pct:+.2f}%）"

    # 给你真实账户挂单建议（短）
    advice = []
    for f in sold:
        tag = "止损卖" if "止损" in str(f.get("reason")) else "止盈卖"
        advice.append({
            "action": "SELL",
            "code": f["code"],
            "name": f.get("name"),
            "price": f["price"],
            "hint": f"{tag} —— 可用限价 {f['price']:.2f} 附近挂单",
        })
    for f in bought:
        advice.append({
            "action": "BUY",
            "code": f["code"],
            "name": f.get("name"),
            "price": f["price"],
            "stop": f.get("stop"),
            "target": f.get("target"),
            "hint": (
                f"回踩可买，限价建议 {f['price']*0.995:.2f}~{f['price']:.2f}；"
                f"止损 {f.get('stop')} / 目标 {f.get('target')}"
            ),
        })
    # 未成交但仍值得挂观察
    bought_codes = {f["code"] for f in bought}
    for b in buys_plan:
        if b["code"] in bought_codes:
            continue
        advice.append({
            "action": "WATCH_BUY",
            "code": b["code"],
            "name": b["name"],
            "price": b["price"],
            "stop": b["stop"],
            "target": b["target"],
            "hint": f"仓位满或未模拟成交：可挂观察单 {b['support']:.2f}~{b['price']:.2f}",
        })

    if not advice:
        if snap["positions"]:
            advice.append({
                "action": "HOLD",
                "hint": "无新挂单。持仓继续拿，不破止损不乱卖。",
            })
        else:
            advice.append({
                "action": "IDLE",
                "hint": "空仓观望：盘中无买入提醒，收盘扫描也无强买点。",
            })

    return {
        "date": today,
        "verdict": verdict,
        "day_pnl": day_pnl,
        "day_pct": day_pct,
        "realized_pnl": realized,
        "cum_pnl": snap["cum_pnl"],
        "cum_pct": snap["cum_pct"],
        "total": snap["total"],
        "cash": snap["cash"],
        "positions": snap["positions"],
        "fills": fills,
        "advice": advice,
        "fee_note": f"佣金万{COMMISSION_RATE*10000:.1f}/最低{MIN_COMMISSION}元，卖印花{STAMP_TAX_RATE*1000:.1f}‰",
    }


def render_markdown(c: dict) -> str:
    """短报告：结论优先，给你挂单。"""
    now = datetime.now().strftime("%H:%M")
    sign = "🟢" if c["day_pnl"] >= 0 else "🔴"
    lines = [
        f"# 波段结论 {c['date']} {now}",
        "",
        f"## {sign} {c['verdict']}",
        f"累计：¥{c['cum_pnl']:+.0f}（{c['cum_pct']:+.2f}%）| 总资产 {c['total']:.0f} | 现金 {c['cash']:.0f}",
        f"今日已实现卖出盈亏：¥{c['realized_pnl']:+.0f}",
        "",
        "## 给你挂单建议（实盘参考）",
    ]
    for a in c["advice"]:
        if a["action"] in ("BUY", "SELL", "WATCH_BUY"):
            lines.append(
                f"- **{a['action']} {a.get('name','')}({a.get('code','')})** @ {a.get('price',0):.2f} — {a['hint']}"
            )
        else:
            lines.append(f"- {a['hint']}")
    lines.append("")
    lines.append("## 波段模拟持仓")
    if not c["positions"]:
        lines.append("> 空仓")
    else:
        for p in c["positions"]:
            lines.append(
                f"- {p['name']}({p['code']}) {p['qty']}股 成本{p['cost']:.2f} "
                f"现价{p['price']:.2f} {p['pnl_pct']:+.1f}% | 止损{p['stop']} 目标{p['target']}"
            )
    lines.append("")
    lines.append("## 今日模拟成交")
    ok_fills = [f for f in c["fills"] if f.get("ok")]
    if not ok_fills:
        lines.append("> 无成交")
    else:
        for f in ok_fills:
            lines.append(
                f"- {f['side']} {f.get('name')}({f['code']}) {f.get('qty')}股 "
                f"@{f.get('price'):.2f} — {f.get('reason')}"
            )
    lines.append("")
    lines.append(f"> {c['fee_note']} | 模拟账户 #{SWING_ACCOUNT_ID} | 非投资承诺")
    return "\n".join(lines)


def push_report(md: str) -> bool:
    ok = _push_markdown_raw(md)
    if ok:
        return True
    try:
        from notifier.wecom_notifier import push_text
        return bool(push_text(md[:1500]))
    except Exception as e:
        log.warning("推送失败: %s", e)
        return False


def _push_markdown_raw(md: str) -> bool:
    import yaml
    url = None
    for name in ("config.local.yaml", "config.yaml"):
        p = ROOT / name
        if not p.exists():
            continue
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        url = (data.get("notify") or {}).get("wecom_webhook") or (data.get("notifier") or {}).get("wecom_webhook")
        if url and "YOUR_KEY" not in url:
            break
        url = None
    if not url:
        log.warning("无有效 webhook，仅落盘")
        return False
    payload = json.dumps(
        {"msgtype": "markdown", "markdown": {"content": md[:3500]}},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
            return body.get("errcode") == 0
    except Exception as e:
        log.error("企微失败: %s", e)
        return False


def save_daily(concl: dict, md: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    day = concl["date"]
    path = OUT_DIR / f"{day}.md"
    path.write_text(md, encoding="utf-8")
    (OUT_DIR / f"{day}.json").write_text(json.dumps(concl, ensure_ascii=False, indent=2), encoding="utf-8")
    conn = _conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS swing_daily_conclusions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT UNIQUE,
                headline TEXT,
                payload_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "INSERT INTO swing_daily_conclusions (report_date, headline, payload_json) VALUES (?,?,?) "
            "ON CONFLICT(report_date) DO UPDATE SET headline=excluded.headline, "
            "payload_json=excluded.payload_json, created_at=CURRENT_TIMESTAMP",
            (day, concl["verdict"], json.dumps(concl, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
    return path


def _norm(live: list[dict]) -> list[dict]:
    out = []
    for r in live:
        out.append({
            "code": r.get("code"), "stock_code": r.get("code"),
            "name": r.get("name"), "stock_name": r.get("name"),
            "price": r.get("price"), "score": r.get("score"),
            "signal_type": r.get("signal_type"), "signals": r.get("signals"),
            "support": r.get("support"), "resist": r.get("resist"),
            "net_rr": r.get("net_rr"), "risk_reward": r.get("risk_reward"),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-scan", action="store_true")
    ap.add_argument("--no-trade", action="store_true", help="不模拟成交，只出建议")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    today = date.today().isoformat()
    ensure_swing_account()

    # 今日动态池缺失则补建（方法过滤 + 软上限50）
    try:
        from swing_pool_builder import ensure_today_pool
        ensure_today_pool(max_pool=50, min_score=70)
    except Exception as e:
        log.warning("ensure_today_pool 失败，将回退种子池: %s", e)

    # 盘前净值（交易前）
    before = snapshot()
    prev = prev_nav(today)
    if prev is None:
        # 第一次：用交易前总资产当地初日基准
        baseline = before["total"]
    else:
        baseline = prev

    if args.skip_scan:
        # REQ-100: 先刷持仓价，扫池失败也不影响盯市
        marked = refresh_and_mark(load_positions())
        scan_rows = load_scan_results(today)
        if not scan_rows:
            try:
                scan_rows = _norm(run_scan())
            except Exception as e:
                log.warning("run_scan 失败（已刷价）: %s", e)
                scan_rows = []
    else:
        marked = refresh_and_mark(load_positions())
        try:
            scan_rows = _norm(run_scan())
        except Exception as e:
            log.warning("run_scan 失败（已刷价）: %s", e)
            scan_rows = []

    scan_buys = pick_buys(scan_rows, marked)
    # 盘中已提醒但未成交的 BUY 要补漏（避免「10:05提醒买、16:05说空仓」）
    already = today_bought_codes(today) | {
        str(p["stock_code"]).zfill(6)[-6:] for p in marked
    }
    intraday = [
        b for b in load_intraday_buy_alerts(today)
        if b["code"] not in already
    ]
    buys = merge_buys(scan_buys, intraday, marked)
    if intraday:
        log.info("盘中补漏候选 %d: %s", len(intraday), [b["code"] for b in intraday])

    fills: list[dict] = []
    if not args.no_trade:
        fills = execute_sim(marked, buys)
        # 收盘补漏成交也立刻 @all，别等整份日报被淹没
        if fills and not args.no_push:
            try:
                from swing_intraday_watch import push_sync_trade
                for f in fills:
                    if f.get("ok"):
                        push_sync_trade(f)
                        time.sleep(0.3)
            except Exception as e:
                log.warning("同步实盘提醒失败: %s", e)
    else:
        # 仅建议：把拟买卖写进 advice，不写成交
        for p in marked:
            if p["action"].startswith("SELL"):
                fills.append({
                    "ok": False, "code": p["stock_code"], "name": p.get("stock_name"),
                    "side": "SELL", "price": p["current_price"], "qty": p["quantity"],
                    "reason": f"[未成交]{p['action_reason']}",
                })

    after = snapshot()
    write_nav(today, after)
    day_pnl = after["total"] - baseline
    day_pct = (day_pnl / baseline * 100) if baseline else 0.0

    # no-trade 时把计划买入塞进 advice 用的 buys
    concl = build_conclusion(today, after, fills, buys, day_pnl, day_pct)
    if args.no_trade:
        # 覆盖 advice：用计划而非成交
        advice = []
        for p in marked:
            if p["action"].startswith("SELL"):
                tag = "止损" if p["action"] == "SELL_STOP" else "止盈"
                advice.append({
                    "action": "SELL", "code": p["stock_code"], "name": p.get("stock_name"),
                    "price": p["current_price"],
                    "hint": f"{tag}建议 —— 限价 {p['current_price']:.2f} 附近",
                })
        for b in buys:
            advice.append({
                "action": "BUY", "code": b["code"], "name": b["name"], "price": b["price"],
                "stop": b["stop"], "target": b["target"],
                "hint": f"限价 {b['support']:.2f}~{b['price']:.2f}；止损{b['stop']} 目标{b['target']}",
            })
        if not advice:
            advice = [{"action": "IDLE", "hint": "无挂单动作，空仓/持仓观望。"}]
        concl["advice"] = advice
        concl["verdict"] = "（仅建议未模拟成交）" + concl["verdict"]

    md = render_markdown(concl)
    path = save_daily(concl, md)
    log.info("写报告 %s", path)
    log.info("%s", concl["verdict"])

    if not args.no_push:
        log.info("推送 %s", "OK" if push_report(md) else "FAIL/SKIP")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
