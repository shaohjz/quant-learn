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

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import swing_daily_report as sdr

from quant_core.bank_swing_pool import get_bank_pool
from quant_core.swing_params import load_swing_params
from sim.config import account_initial_cash
from sim.config_resolver import resolve_artifact_root

BANK_ACCOUNT_ID = 4
# 银行池在 config.yaml 里的人工声明段。留空则沿用 swing_strategy 的默认值。
BANK_SECTION = "bank_swing_strategy"

# 读不到账户初始资金时的兜底值，与 sim/config.py 的 _ACCOUNT_FALLBACK[4] 对齐。
_FALLBACK_INITIAL_CASH = 30_000.0

# sim.config.load_config 自身不做异常兜底，读账户资金时可能外泄的故障面就这些：
#   OSError        config.yaml / config.local.yaml 缺失、无权限、被其它进程占用
#   yaml.YAMLError 人工编辑 yaml 留下语法错误
#   ValueError     initial_cash / account_id / QUANT_INITIAL_CASH 不是合法数字
#   TypeError      配置项类型不对
#   RuntimeError   pyyaml 未安装（sim.config 里也是这么抛的）
# 只兜底配置读取这一类故障，不放任 KeyboardInterrupt 之类被吞掉。
_CONFIG_ERRORS = (OSError, yaml.YAMLError, ValueError, TypeError, RuntimeError)


def apply_bank_profile() -> None:
    """把通用波段日报切到银行专用 profile（模块级开关，进程内一次）。"""
    # logger 先切，后面读配置失败时的兜底日志才不会记到通用波段的 logger 上
    sdr.log = sdr.logging.getLogger("bank_swing_daily")
    sdr.SWING_ACCOUNT_ID = BANK_ACCOUNT_ID
    sdr.SWING_ACCOUNT_NAME = "bank_swing"
    try:
        sdr.SWING_INITIAL_CASH = float(account_initial_cash(BANK_ACCOUNT_ID))
    except _CONFIG_ERRORS as exc:
        sdr.log.warning(
            "读取账户 #%s 初始资金失败，兜底 %.0f 元：%s",
            BANK_ACCOUNT_ID,
            _FALLBACK_INITIAL_CASH,
            exc,
        )
        sdr.SWING_INITIAL_CASH = _FALLBACK_INITIAL_CASH

    # 银行独立参数。刻意不套用机器自动调参层（auto_overrides）——那层的证据
    # 来自账户 #3 的样本，级联过来会让一次自动调参同时影响两个结论不同的账户。
    bank_params = load_swing_params(section=BANK_SECTION, auto_overrides={})
    sdr.PARAMS = bank_params
    # scan_stock 缺省读 swing_auto.PARAMS（#3）。进程内一并切过去，
    # 避免漏传 params= 时银行扫描仍按 1.2 / 0.8 把票滤光。
    import swing_auto as _sa
    _sa.PARAMS = bank_params
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


def main() -> int:
    apply_bank_profile()
    return sdr.main()


if __name__ == "__main__":
    raise SystemExit(main())
