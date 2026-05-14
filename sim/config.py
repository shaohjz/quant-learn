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
        "max_daily_trades": int(get("risk.max_daily_trades", 5)),
        "stop_loss_pct": float(get("risk.stop_loss_pct", -0.08)),
        "take_profit_pct": float(get("risk.take_profit_pct", 0.15)),
    }


def broker_mode() -> str:
    return os.environ.get("BROKER_MODE",
                          get("broker.mode", "sim")).lower()
