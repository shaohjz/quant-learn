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


def get_account_config(account_id: int | str = 1) -> dict:
    """Return merged config for an account id.

    The project now keeps dual-account settings under ``accounts.learn`` and
    ``accounts.real``.  Older code paths still ask by numeric account id, so this
    helper centralises the mapping and applies ``config.local.yaml`` overrides
    via ``load_config()``.
    """
    aid = int(account_id)
    cfg = load_config()
    accounts = cfg.get("accounts") or {}
    for key, val in accounts.items():
        if isinstance(val, dict) and int(val.get("account_id", -1)) == aid:
            out = dict(val)
            out.setdefault("key", key)
            out.setdefault("account_name", "live_mirror" if aid == 1 else "real_portfolio")
            out.setdefault("initial_cash", 100000.0 if aid == 1 else 25000.0)
            return out

    # Backward-compatible fallback when config lacks the new accounts block.
    key = "learn" if aid == 1 else "real"
    return {
        "key": key,
        "account_id": aid,
        "account_name": "live_mirror" if aid == 1 else "real_portfolio",
        "initial_cash": float(os.environ.get("QUANT_INITIAL_CASH", get("account.initial_cash", 100000.0 if aid == 1 else 25000.0))),
        "auto_trade": aid == 1,
    }


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
    }


def broker_mode() -> str:
    return os.environ.get("BROKER_MODE",
                          get("broker.mode", "sim")).lower()
