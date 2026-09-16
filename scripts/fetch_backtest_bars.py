#!/usr/bin/env python3
"""拉取中长线回测用日线，写入 data/backtest_bars/。

优先腾讯前复权日 K（与 swing_auto.get_kline 同源），失败则跳过该标的。
已有本地 CSV 会一并复制进去，方便离线重跑。
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from quant_core.bank_swing_pool import BANK_POOL  # noqa: E402

OUT = ROOT / "data" / "backtest_bars"
SRC_DATA = ROOT / "data"


def _prefixed(code: str) -> str:
    c6 = "".join(ch for ch in str(code) if ch.isdigit()).zfill(6)[-6:]
    return ("sh" if c6.startswith(("5", "6", "9")) else "sz") + c6


def collect_codes() -> dict[str, str]:
    codes: dict[str, str] = {}
    for path in sorted(SRC_DATA.glob("*.csv")):
        stem = path.stem
        if stem.isdigit() and len(stem) == 6:
            codes[stem] = stem
    for prefixed, name in BANK_POOL:
        c6 = prefixed[-6:]
        codes[c6] = name
    try:
        import swing_auto as _sa

        STOCK_POOL = list(_sa.STOCK_POOL)
    except Exception:
        STOCK_POOL = []
    for prefixed, name in STOCK_POOL:
        c6 = "".join(ch for ch in prefixed if ch.isdigit())[-6:]
        if len(c6) == 6:
            codes[c6] = name
    return codes


def fetch_tencent(code6: str, days: int = 900) -> list[dict] | None:
    prefixed = _prefixed(code6)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefixed},day,,,{days},qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode("utf-8"))
        blob = data.get("data", {}).get(prefixed, {}) or {}
        rows = blob.get("qfqday") or blob.get("day") or []
        out = []
        for row in rows:
            out.append(
                {
                    "date": row[0],
                    "open": float(row[1]),
                    "close": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "volume": float(row[5]),
                    "symbol": code6,
                    "adjustment_type": "qfq",
                }
            )
        return out or None
    except Exception as exc:
        print(f"  skip {code6}: {exc}")
        return None


def write_csv(code6: str, rows: list[dict]) -> None:
    path = OUT / f"{code6}.csv"
    fields = ["date", "open", "high", "low", "close", "volume", "symbol", "adjustment_type"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    codes = collect_codes()
    print(f"准备拉取 {len(codes)} 只，输出 {OUT}")
    ok = 0
    for i, (code6, name) in enumerate(sorted(codes.items()), 1):
        rows = fetch_tencent(code6)
        if not rows:
            continue
        write_csv(code6, rows)
        ok += 1
        print(f"[{i}/{len(codes)}] {code6} {name}  {rows[0]['date']} → {rows[-1]['date']}  n={len(rows)}")
        time.sleep(0.12)
    print(f"完成 {ok}/{len(codes)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
