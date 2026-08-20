"""scripts/bank_swing_daily.py — 银行股专用波段日报

账户 #4 (bank_swing)，独立池、独立结论「银行波段结论」，不被 #3 通用波段满仓挤掉。

复用 swing_daily_report 的扫/买/卖/净值/推送逻辑，仅切换 profile。

用法：
  python scripts/bank_swing_daily.py
  python scripts/bank_swing_daily.py --no-trade
  python scripts/bank_swing_daily.py --no-push
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import swing_daily_report as sdr  # noqa: E402
from quant_core.bank_swing_pool import get_bank_pool  # noqa: E402
from sim.config import account_initial_cash  # noqa: E402
from sim.config_resolver import resolve_artifact_root  # noqa: E402

BANK_ACCOUNT_ID = 4
BANK_MAX_POSITIONS = 3
BANK_SINGLE_BUDGET = 8_000.0


def apply_bank_profile() -> None:
    """把通用波段日报切到银行专用 profile（模块级开关，进程内一次）。"""
    sdr.SWING_ACCOUNT_ID = BANK_ACCOUNT_ID
    sdr.SWING_ACCOUNT_NAME = "bank_swing"
    try:
        sdr.SWING_INITIAL_CASH = float(account_initial_cash(BANK_ACCOUNT_ID))
    except Exception:
        sdr.SWING_INITIAL_CASH = 30_000.0
    sdr.OUT_DIR = resolve_artifact_root() / "bank_swing_daily"
    sdr.MAX_POSITIONS = BANK_MAX_POSITIONS
    sdr.SINGLE_BUDGET = BANK_SINGLE_BUDGET
    sdr.get_stock_pool = get_bank_pool
    sdr.REPORT_TITLE = "银行波段结论"
    sdr.VERDICT_LABEL = "银行波段"
    sdr.HOLDINGS_LABEL = "银行波段持仓"
    sdr.CONCLUSIONS_TABLE = "bank_swing_daily_conclusions"
    sdr.SKIP_GENERAL_POOL = True
    sdr.SKIP_INTRADAY_MERGE = True
    sdr.log = sdr.logging.getLogger("bank_swing_daily")


def main() -> int:
    apply_bank_profile()
    return sdr.main()


if __name__ == "__main__":
    raise SystemExit(main())
