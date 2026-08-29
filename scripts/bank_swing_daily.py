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
from quant_core.swing_params import load_swing_params
from sim.config import account_initial_cash  # noqa: E402
from sim.config_resolver import resolve_artifact_root  # noqa: E402

BANK_ACCOUNT_ID = 4
# 银行池在 config.yaml 里的人工声明段。留空则沿用 swing_strategy 的默认值。
BANK_SECTION = "bank_swing_strategy"


def apply_bank_profile() -> None:
    """把通用波段日报切到银行专用 profile（模块级开关，进程内一次）。"""
    sdr.SWING_ACCOUNT_ID = BANK_ACCOUNT_ID
    sdr.SWING_ACCOUNT_NAME = "bank_swing"
    try:
        sdr.SWING_INITIAL_CASH = float(account_initial_cash(BANK_ACCOUNT_ID))
    except Exception:
        sdr.SWING_INITIAL_CASH = 30_000.0

    # 银行独立参数。刻意不套用机器自动调参层（auto_overrides）——那层的证据
    # 来自账户 #3 的样本，级联过来会让一次自动调参同时影响两个结论不同的账户。
    bank_params = load_swing_params(section=BANK_SECTION, auto_overrides={})
    sdr.PARAMS = bank_params
    sdr.STOP_LOSS_PCT = bank_params.stop_loss_pct
    sdr.TAKE_PROFIT_PCT = bank_params.take_profit_pct
    sdr.MIN_SCORE_BUY = bank_params.min_score_buy
    sdr.EXECUTABLE_TYPES = set(bank_params.executable_types)
    sdr.MAX_POSITIONS = bank_params.max_positions
    sdr.SINGLE_BUDGET = bank_params.single_budget
    # 费率按银行真实建仓预算试算，否则低价银行股会被最低佣金 5 元误杀
    sdr.SCAN_FEE_BUDGET = bank_params.single_budget

    sdr.OUT_DIR = resolve_artifact_root() / "bank_swing_daily"
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
