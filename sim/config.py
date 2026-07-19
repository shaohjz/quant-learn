"""
sim/config.py — 配置加载

读取项目根目录的 config.yaml，并允许 config.local.yaml 覆盖（敏感字段）。
"""

import os
from functools import lru_cache
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_FILE = _PROJECT_ROOT / "config.yaml"
_LOCAL_FILE = _PROJECT_ROOT / "config.local.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并两个 dict（override 覆盖 base）"""
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@lru_cache(maxsize=1)
def load_config() -> dict:
    if yaml is None:
        raise RuntimeError("需要安装 pyyaml: pip install pyyaml")

    cfg = {}
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    if _LOCAL_FILE.exists():
        with open(_LOCAL_FILE, "r", encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, local)
    return cfg


def get(path: str, default=None):
    """按点路径读取配置：get('risk.stop_loss_pct')"""
    cfg = load_config()
    cur = cfg
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


# 常用快捷
def initial_cash() -> float:
    return float(os.environ.get("QUANT_INITIAL_CASH",
                                get("account.initial_cash", 20000)))


# account_id → 兜底元数据。仅当 config.yaml 的 accounts.* 缺该账户时使用。
# 资金真源永远是 config.yaml；这里只是防止 config 缺失时用一个可预期的默认值，
# 避免各模块各写一套硬编码（历史上出现过 20000/100000/200000/50000 混用）。
_ACCOUNT_FALLBACK: dict[int, dict] = {
    1: {"key": "learn", "account_name": "learn", "initial_cash": 100000.0},
    2: {"key": "real", "account_name": "real_portfolio", "initial_cash": 25000.0},
    3: {"key": "swing", "account_name": "swing_trade", "initial_cash": 50000.0},
}


def _account_fallback(aid: int) -> dict:
    return _ACCOUNT_FALLBACK.get(
        aid,
        {"key": f"acct{aid}", "account_name": f"account_{aid}", "initial_cash": 100000.0},
    )


def get_account_config(account_id: int | str = 1) -> dict:
    """按 account_id 返回账户配置。config.yaml 的 accounts.* 是唯一真源。

    所有需要「初始资金 / 总额上限 / 账户名」的模块都应经此函数取值，
    不要再各自 `'learn' if id==1 else 'real'` 或硬编码默认金额。
    匹配规则：遍历 accounts.* 用 account_id 匹配；缺失时用 _ACCOUNT_FALLBACK 兜底。
    """
    aid = int(account_id)
    fb = _account_fallback(aid)
    cfg = load_config()
    accounts = cfg.get("accounts") or {}
    for key, val in accounts.items():
        if isinstance(val, dict) and int(val.get("account_id", -1)) == aid:
            out = dict(val)
            out.setdefault("key", key)
            out.setdefault("account_name", fb["account_name"])
            out.setdefault("initial_cash", fb["initial_cash"])
            return out

    # config 缺该账户 → 兜底（含环境变量覆盖）
    return {
        "key": fb["key"],
        "account_id": aid,
        "account_name": fb["account_name"],
        "initial_cash": float(
            os.environ.get("QUANT_INITIAL_CASH", get("account.initial_cash", fb["initial_cash"]))
        ),
        "auto_trade": aid == 1,
    }


def account_key(account_id: int | str = 1) -> str:
    """account_id → config key（learn/real/swing/...）。"""
    return str(get_account_config(account_id).get("key"))


def account_name(account_id: int | str = 1) -> str:
    return str(get_account_config(account_id).get("account_name") or "")


def account_initial_cash(account_id: int | str = 1) -> float:
    """账户声明的初始资金（config 真源）。NAV 基准仍以 DB.initial_cash 为准（REQ-094）。"""
    return float(get_account_config(account_id).get("initial_cash") or 0.0)


def account_max_total_value(account_id: int | str = 1) -> float:
    """账户总额上限；未配置 max_total_value 时回退到 initial_cash。"""
    acct = get_account_config(account_id)
    return float(acct.get("max_total_value") or acct.get("initial_cash") or 0.0)


def stock_pool_enabled() -> dict:
    """返回启用的 {code: name}"""
    pool = get("stock_pool", []) or []
    out = {}
    for item in pool:
        if item.get("enabled", True):
            out[item["code"]] = item.get("name", "")
    return out


def risk_params() -> dict:
    return {
        "max_position_pct": float(get("risk.max_position_pct", 0.60)),
        "max_total_positions": int(get("risk.max_total_positions", 6)),
        "max_daily_new_positions": int(get("risk.max_daily_new_positions", 3)),
        "max_daily_trades": int(get("risk.max_daily_trades", 5)),
        "max_daily_build_amount_pct": float(get("risk.max_daily_build_amount_pct", 0.30)),
        "liquidity_release_loss_threshold": float(get("risk.liquidity_release_loss_threshold", 0.08)),
        "stop_loss_pct": float(get("risk.stop_loss_pct", -0.08)),
        "take_profit_pct": float(get("risk.take_profit_pct", 0.15)),
        # [REQ-036] 行业/板块集中度风控
        "max_industry_pct": float(get("risk.max_industry_pct", 0.30)),
        "max_sector_pct": float(get("risk.max_sector_pct", 0.35)),
        "warn_industry_pct": float(get("risk.warn_industry_pct", 0.25)),
        "warn_sector_pct": float(get("risk.warn_sector_pct", 0.30)),
    }


def broker_mode() -> str:
    return os.environ.get("BROKER_MODE",
                          get("broker.mode", "sim")).lower()
