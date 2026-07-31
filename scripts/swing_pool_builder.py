"""scripts/swing_pool_builder.py — 每日动态稳定波段池（方法过滤 + 软上限）

从沪深300+中证500（~800）用硬过滤筛合格票（流动性/价位/ATR/振幅/回撤），
再按稳定性分 ≥ min_score 入池；人数过多时按分截断到 max_pool（默认 50）。
不是死卡「Top20」：先方法、后软上限。持仓股强制保留（方便盯止盈止损）。

周末/休市：--mode hist（或 auto）用日K历史收盘+均成交额估流动性，照样能扫。

输出：
  output/swing_pool/YYYY-MM-DD.json
  output/swing_pool/latest.json

用法：
  python scripts/swing_pool_builder.py
  python scripts/swing_pool_builder.py --max-pool 50 --min-score 70 --mode hist --force
  python scripts/swing_pool_builder.py --max-pool 50 --limit 80
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from swing_auto import STOCK_POOL, get_kline, get_quote  # noqa: E402
from sim.config_resolver import resolve_artifact_root, resolve_db_path  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("swing_pool")

OUT_DIR = resolve_artifact_root() / "swing_pool"
UNIVERSE_CACHE = ROOT / "data" / "universe_cache.json"
DB_PATH = resolve_db_path()
SWING_ACCOUNT_ID = 3

DEFAULT_MAX_POOL = 50  # 软上限：Pulse 每 10 分要扫完，别涨到 300+
DEFAULT_MIN_SCORE = 70.0  # 稳定性分地板（硬过滤过了还得够格）
MIN_AMOUNT = 1e8  # 1 亿
MIN_PRICE = 5.0
MAX_PRICE = 200.0
ATR_MIN = 1.5
ATR_MAX = 5.5
ATR_SWEET = 3.0
MAX_AVG_AMP = 6.0
MAX_DROP_5D = -8.0


def to_prefixed(code6: str) -> str:
    c = str(code6).zfill(6)[-6:]
    return ("sh" if c.startswith(("5", "6", "9")) else "sz") + c


def to_code6(code: str) -> str:
    return str(code).replace("sh", "").replace("sz", "").zfill(6)[-6:]


def load_universe() -> list[str]:
    """6 位代码列表：优先本地缓存，否则用 STOCK_POOL 兜底。"""
    if UNIVERSE_CACHE.exists():
        try:
            data = json.loads(UNIVERSE_CACHE.read_text(encoding="utf-8"))
            codes = [to_code6(c) for c in data.get("codes", [])]
            codes = sorted({c for c in codes if c.isdigit() and len(c) == 6})
            if len(codes) >= 50:
                log.info("宇宙(缓存): %d 只", len(codes))
                return codes
        except Exception as e:
            log.warning("读 universe_cache 失败: %s", e)
    seed = [to_code6(c) for c, _ in STOCK_POOL]
    log.warning("宇宙缓存不可用，回退种子池 %d 只", len(seed))
    return seed


def load_held_codes() -> set[str]:
    if not DB_PATH.exists():
        return set()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        rows = conn.execute(
            "SELECT stock_code FROM sim_positions WHERE account_id=? AND quantity>0",
            (SWING_ACCOUNT_ID,),
        ).fetchall()
        return {to_code6(r[0]) for r in rows}
    except sqlite3.OperationalError:
        return set()
    finally:
        conn.close()


def load_prev_pool() -> dict:
    latest = OUT_DIR / "latest.json"
    if not latest.exists():
        return {}
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return {}


def calc_atr_pct(klines: list[dict]) -> float | None:
    if not klines or len(klines) < 14:
        return None
    recent = klines[-14:]
    atr = sum(k["high"] - k["low"] for k in recent) / len(recent)
    last = recent[-1]["close"]
    if last <= 0:
        return None
    return atr / last * 100


def calc_avg_amp(klines: list[dict]) -> float | None:
    if not klines or len(klines) < 6:
        return None
    amps = []
    for i in range(-5, 0):
        prev = klines[i - 1]["close"]
        if prev <= 0:
            continue
        amps.append((klines[i]["high"] - klines[i]["low"]) / prev * 100)
    return sum(amps) / len(amps) if amps else None


def calc_max_drop_5d(klines: list[dict]) -> float | None:
    if not klines or len(klines) < 6:
        return None
    drops = []
    for i in range(-5, 0):
        prev = klines[i - 1]["close"]
        if prev <= 0:
            continue
        drops.append((klines[i]["close"] - prev) / prev * 100)
    return min(drops) if drops else None


def hard_filter_spot(name: str, price: float, amount: float) -> str | None:
    """不通过返回原因，通过返回 None。"""
    if "ST" in (name or "").upper():
        return "ST"
    if price < MIN_PRICE or price > MAX_PRICE:
        return "price"
    if amount < MIN_AMOUNT:
        return "amount"
    return None


def hard_filter_kline(atr_pct: float | None, avg_amp: float | None, max_drop: float | None) -> str | None:
    if atr_pct is None or avg_amp is None or max_drop is None:
        return "kline"
    if atr_pct < ATR_MIN or atr_pct > ATR_MAX:
        return "atr"
    if avg_amp > MAX_AVG_AMP:
        return "amp"
    if max_drop < MAX_DROP_5D:
        return "drop"
    return None


def stability_score(atr_pct: float, avg_amp: float, amount: float, max_drop: float) -> float:
    """越高越适合做稳定波段。每日重排 → 优胜劣汰。"""
    # ATR 越靠近甜区越好（峰值 50）
    atr_score = max(0.0, 50.0 - abs(atr_pct - ATR_SWEET) * 12.0)
    # 振幅越低越好（峰值 25）
    amp_score = max(0.0, 25.0 - avg_amp * 3.0)
    # 流动性：成交额对数（峰值 ~25）
    liq = min(25.0, max(0.0, (amount / 1e8) ** 0.5 * 5.0))
    # 近 5 日别太惨（峰值 10）
    drop_score = max(0.0, 10.0 + max_drop)  # max_drop 通常负
    return round(atr_score + amp_score + liq + drop_score, 2)


def estimate_amount_from_kline(klines: list[dict], days: int = 5) -> float:
    """用近 N 日均成交额估流动性。腾讯日K volume 多为「手」→ ×100×收盘价。"""
    if not klines:
        return 0.0
    recent = klines[-days:]
    amts = []
    for k in recent:
        vol = float(k.get("volume") or 0)
        close = float(k.get("close") or 0)
        if vol > 0 and close > 0:
            amts.append(vol * 100.0 * close)
    return sum(amts) / len(amts) if amts else 0.0


def is_weekend() -> bool:
    return date.today().weekday() >= 5


def evaluate_one(code6: str, mode: str = "auto") -> dict | None:
    """mode: auto|live|hist。周末/auto 默认走日K历史，不依赖盘中成交额。"""
    pref = to_prefixed(code6)
    use_hist = mode == "hist" or (mode == "auto" and is_weekend())

    name = code6
    price = 0.0
    amount = 0.0
    asof = None
    fell_back = False

    if not use_hist:
        quote = get_quote(pref)
        if quote and quote.get("price", 0) > 0:
            name = quote.get("name") or code6
            price = float(quote["price"])
            # 腾讯 qt 成交额单位为「万元」
            amount = float(quote.get("amount") or 0) * 10000.0

    klines = get_kline(pref, 30)
    if not klines or len(klines) < 20:
        return None

    if use_hist or price <= 0:
        if not use_hist:
            fell_back = True
        price = float(klines[-1]["close"])
        amount = estimate_amount_from_kline(klines)
        asof = klines[-1].get("date")
        if name == code6:
            try:
                q = get_quote(pref)
                if q and q.get("name"):
                    name = q["name"]
            except Exception:
                pass

    reason = hard_filter_spot(name, price, amount)
    if reason:
        return None

    atr_pct = calc_atr_pct(klines)
    avg_amp = calc_avg_amp(klines)
    max_drop = calc_max_drop_5d(klines)
    reason = hard_filter_kline(atr_pct, avg_amp, max_drop)
    if reason:
        return None

    score = stability_score(atr_pct, avg_amp, amount, max_drop)
    data_mode = "hist" if (use_hist or fell_back) else "live"
    out = {
        "code": code6,
        "prefixed": pref,
        "name": name,
        "price": price,
        "amount": amount,
        "atr_pct": round(atr_pct, 2),
        "avg_amp": round(avg_amp, 2),
        "max_drop_5d": round(max_drop, 2),
        "stability_score": score,
        "protected": False,
        "data_mode": data_mode,
    }
    if asof:
        out["asof"] = asof
    return out


def select_pool(
    candidates: list[dict],
    held: set[str],
    max_pool: int = DEFAULT_MAX_POOL,
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[dict]:
    """方法入池：硬过滤已过的候选里，分≥min_score 全收；超 max_pool 按分截断。持仓强制保留。"""
    by_code = {c["code"]: dict(c) for c in candidates}
    selected: list[dict] = []
    used: set[str] = set()

    for code in held:
        if code in by_code:
            item = by_code[code]
            item["protected"] = True
            selected.append(item)
            used.add(code)
        else:
            # 持仓不在候选里也留坑：用最小信息占位，盘中仍可盯卖
            selected.append({
                "code": code,
                "prefixed": to_prefixed(code),
                "name": code,
                "price": 0,
                "amount": 0,
                "atr_pct": 0,
                "avg_amp": 0,
                "max_drop_5d": 0,
                "stability_score": -1,
                "protected": True,
            })
            used.add(code)

    ranked = sorted(
        (
            c for c in candidates
            if c["code"] not in used and float(c.get("stability_score") or 0) >= min_score
        ),
        key=lambda x: x["stability_score"],
        reverse=True,
    )
    for c in ranked:
        if len(selected) >= max_pool:
            break
        selected.append(c)
        used.add(c["code"])

    selected.sort(key=lambda x: (not x.get("protected"), -x["stability_score"]))
    # 持仓保护可略超 max_pool（盯止盈止损优先）
    non_prot = [x for x in selected if not x.get("protected")]
    prot = [x for x in selected if x.get("protected")]
    room = max(0, max_pool - len(prot))
    return prot + non_prot[:room]


def churn(prev_codes: set[str], new_codes: set[str]) -> dict:
    return {
        "entered": sorted(new_codes - prev_codes),
        "exited": sorted(prev_codes - new_codes),
        "kept": sorted(prev_codes & new_codes),
    }


def build_pool(
    max_pool: int = DEFAULT_MAX_POOL,
    min_score: float = DEFAULT_MIN_SCORE,
    limit: int | None = None,
    workers: int = 8,
    mode: str = "auto",
    top: int | None = None,
) -> dict:
    if top is not None:
        max_pool = top
    universe = load_universe()
    if limit:
        universe = universe[:limit]
    held = load_held_codes()
    effective = "hist" if (mode == "hist" or (mode == "auto" and is_weekend())) else "live"
    log.info(
        "扫描 %d 只 | 持仓保护 %d | min_score≥%.1f | max_pool %d | 数据=%s",
        len(universe), len(held), min_score, max_pool, effective,
    )

    candidates: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(evaluate_one, c, mode): c for c in universe}
        for fut in as_completed(futs):
            done += 1
            if done % 50 == 0:
                log.info("进度 %d/%d，候选 %d", done, len(universe), len(candidates))
            try:
                r = fut.result()
            except Exception:
                r = None
            if r:
                candidates.append(r)
            time.sleep(0.01)

    pool = select_pool(candidates, held, max_pool=max_pool, min_score=min_score)
    prev = load_prev_pool()
    prev_codes = {to_code6(x.get("code", "")) for x in prev.get("stocks", []) if x.get("code")}
    new_codes = {x["code"] for x in pool}
    change = churn(prev_codes, new_codes)
    above_floor = sum(1 for c in candidates if float(c.get("stability_score") or 0) >= min_score)

    payload = {
        "date": date.today().isoformat(),
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "selection": "method+cap",
        "min_score": min_score,
        "max_pool": max_pool,
        "top": max_pool,  # 兼容旧字段
        "data_mode": effective,
        "universe_scanned": len(universe),
        "candidates": len(candidates),
        "above_min_score": above_floor,
        "held_protected": sorted(held),
        "churn": change,
        "stocks": pool,
    }
    return payload


def save_pool(payload: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    day = payload["date"]
    day_path = OUT_DIR / f"{day}.json"
    latest = OUT_DIR / "latest.json"
    # 空池不覆盖 latest，避免盘中回退抖动；仍写当日文件便于排查
    if not payload.get("stocks"):
        log.warning("候选为 0，不覆盖 latest.json（保留旧池或走种子兜底）")
        day_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return latest if latest.exists() else day_path
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    day_path.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    log.info(
        "写池 %s | %d只 | 合格≥%.0f共%d | 新进%d 出局%d 留存%d",
        day_path,
        len(payload["stocks"]),
        float(payload.get("min_score") or 0),
        int(payload.get("above_min_score") or 0),
        len(payload["churn"]["entered"]),
        len(payload["churn"]["exited"]),
        len(payload["churn"]["kept"]),
    )
    return latest


def ensure_today_pool(
    max_pool: int = DEFAULT_MAX_POOL,
    min_score: float = DEFAULT_MIN_SCORE,
    force: bool = False,
    mode: str = "auto",
    top: int | None = None,
) -> Path | None:
    """今日池不存在则构建。供 SwingDaily / 其它入口调用。"""
    if top is not None:
        max_pool = top
    latest = OUT_DIR / "latest.json"
    if not force and latest.exists():
        try:
            data = json.loads(latest.read_text(encoding="utf-8"))
            if data.get("date") == date.today().isoformat() and data.get("stocks"):
                return latest
        except Exception:
            pass
    payload = build_pool(max_pool=max_pool, min_score=min_score, mode=mode)
    return save_pool(payload)


def main() -> int:
    ap = argparse.ArgumentParser(description="每日动态稳定波段池（方法过滤+软上限）")
    ap.add_argument(
        "--max-pool", type=int, default=DEFAULT_MAX_POOL,
        help=f"软上限，默认{DEFAULT_MAX_POOL}（防 Pulse 扫爆）",
    )
    ap.add_argument(
        "--min-score", type=float, default=DEFAULT_MIN_SCORE,
        help=f"稳定性分地板，默认{DEFAULT_MIN_SCORE}（方法合格才入池）",
    )
    ap.add_argument(
        "--top", type=int, default=None,
        help="兼容旧参数：等同 --max-pool",
    )
    ap.add_argument("--limit", type=int, default=None, help="调试：只扫前 N 只")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--mode",
        choices=("auto", "live", "hist"),
        default="auto",
        help="auto=周末自动用日K；hist=强制历史；live=强制实时成交额",
    )
    args = ap.parse_args()
    max_pool = args.top if args.top is not None else args.max_pool

    if not args.force:
        latest = OUT_DIR / "latest.json"
        if latest.exists():
            try:
                data = json.loads(latest.read_text(encoding="utf-8"))
                if data.get("date") == date.today().isoformat() and data.get("stocks"):
                    log.info("今日池已存在 (%d只)，跳过。用 --force 重建", len(data["stocks"]))
                    return 0
            except Exception:
                pass

    payload = build_pool(
        max_pool=max_pool,
        min_score=args.min_score,
        limit=args.limit,
        workers=args.workers,
        mode=args.mode,
    )
    save_pool(payload)
    for s in payload["stocks"][:10]:
        flag = "🔒" if s.get("protected") else "  "
        log.info(
            "%s %s %s score=%.1f atr=%.1f%% [%s]",
            flag, s["code"], s["name"], s["stability_score"], s["atr_pct"],
            s.get("data_mode", "?"),
        )
    if len(payload["stocks"]) > 10:
        log.info("... 共 %d 只", len(payload["stocks"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
