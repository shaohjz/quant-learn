"""quant_core/bank_swing_pool.py — 银行股专用波段池（账户 #4）

与通用 `swing_pool/latest.json` 隔离：只扫银行，结论单独推「银行波段结论」，
避免 #3 满仓锂电/白酒时银行买点永远进不去。
"""
from __future__ import annotations

# (prefixed_code, name) — 与 swing_auto.STOCK_POOL 同格式，供 scan_stock 使用
BANK_POOL: list[tuple[str, str]] = [
    ("sh600036", "招商银行"),
    ("sh601166", "兴业银行"),
    ("sh600000", "浦发银行"),
    ("sh601398", "工商银行"),
    ("sh601939", "建设银行"),
    ("sh601288", "农业银行"),
    ("sh601328", "交通银行"),
    ("sh601988", "中国银行"),
    ("sh601009", "南京银行"),
    ("sh601169", "北京银行"),
    ("sh601818", "光大银行"),
    ("sh600016", "民生银行"),
    ("sh600015", "华夏银行"),
    ("sh601229", "上海银行"),
    ("sz000001", "平安银行"),
    ("sz002142", "宁波银行"),
]


def get_bank_pool(allow_stale: bool = True) -> list[tuple[str, str]]:  # noqa: ARG001
    """银行专用池。签名兼容 swing_auto.get_stock_pool。"""
    return list(BANK_POOL)


def is_bank_code(code: str) -> bool:
    c6 = "".join(ch for ch in str(code or "") if ch.isdigit()).zfill(6)[-6:]
    return any(p[0][-6:] == c6 for p in BANK_POOL)
