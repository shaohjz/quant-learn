"""quant_core/swing_params.py — 账户 #3 波段策略参数（唯一真源）

历史上这些数字散在 `scripts/swing_auto.py`、`swing_daily_report.py`、
`swing_intraday_watch.py` 三处 Python 常量里。后果是研究脚本算出
「min_score 应该是 7」也落不了地——改参数等于改代码 + 重新部署，
反馈闭环在最后一步断掉。

本模块把它们收成一个可加载的参数对象，三层优先级：

1. 本文件 `DEFAULTS` —— 与 2026-07-31 生产行为**逐个数字对齐**（改动前后行为必须一致）
2. `config.yaml` 的 `swing_strategy:` —— 人工声明
3. `config.strategy_params.yaml` —— 机器（每周策略复盘）自动采纳的覆盖层

分成三个文件而不是一个，是为了让「谁改的」一眼可查：
生产基线在代码里、人工调参在 config.yaml、自动调参在独立小文件（便于 diff 与回滚）。
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - 部署文档要求装 pyyaml
    yaml = None

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUTO_PARAMS_FILE = _PROJECT_ROOT / "config.strategy_params.yaml"

# 生产基线：数值来自 2026-07-31 的 swing_auto.py / swing_daily_report.py。
# 改这里等于改生产行为，必须走部署文档。
DEFAULTS: dict[str, dict[str, Any]] = {
    "signals": {
        "a_ma20_tolerance": 0.015,      # A 类：价在 MA20 ±1.5%
        "b_ma10_tolerance": 0.01,       # B 类：价在 MA10 ±1%
        "max_volume_ratio": 0.8,        # A/B 缩量阈值：当日量 / 5日均量
        "quiet_volume_ratio": 0.7,      # E/F 类更严的缩量阈值
        "rsi_oversold": 35.0,           # D 类
        "boll_lower_tolerance": 0.01,   # C 类：价 ≤ 下轨 ×1.01
        "e_min_change_pct": -1.5,       # E 类：三连阴当日跌幅不深于此
        "f_max_change_pct": -2.0,       # F 类：单日跌幅超过此值
    },
    "filters": {
        "min_net_rr": 1.2,              # 扣费后盈亏比下限
        "min_upside_pct": 0.005,        # 预期涨幅下限
        "min_avg_amp": 1.0,             # 近 5 日均振幅下限（%）
    },
    "execution": {
        "min_score_buy": 5,
        "executable_types": ["A", "B"],
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.08,
        "max_positions": 3,
        "single_budget": 10000.0,
    },
}


@dataclass(frozen=True)
class SwingParams:
    """扁平化的波段参数视图。字段名与生产脚本里的旧常量一一对应。"""

    a_ma20_tolerance: float
    b_ma10_tolerance: float
    max_volume_ratio: float
    quiet_volume_ratio: float
    rsi_oversold: float
    boll_lower_tolerance: float
    e_min_change_pct: float
    f_max_change_pct: float
    min_net_rr: float
    min_upside_pct: float
    min_avg_amp: float
    min_score_buy: int
    executable_types: frozenset[str]
    stop_loss_pct: float
    take_profit_pct: float
    max_positions: int
    single_budget: float
    raw: dict = field(default_factory=dict, repr=False, compare=False)
    source_layers: tuple[str, ...] = ()

    def fingerprint(self) -> str:
        """参数指纹，写进信号台账，让「这条信号是哪套参数下产生的」可追溯。"""
        payload = json.dumps(self.raw, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, val in (override or {}).items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load_auto_overrides(path: Path | None = None) -> dict:
    """读机器采纳层。文件不存在（常态）时返回空 dict。"""
    target = path or AUTO_PARAMS_FILE
    if yaml is None or not target.exists():
        return {}
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    params = data.get("swing_strategy")
    return params if isinstance(params, dict) else {}


def resolve_params_dict(
    config: dict | None = None,
    auto_overrides: dict | None = None,
) -> tuple[dict, tuple[str, ...]]:
    """按三层优先级合并，返回 (参数树, 生效层名)。"""
    layers = ["defaults"]
    merged = copy.deepcopy(DEFAULTS)

    declared = ((config or {}).get("swing_strategy") or {}) if config else {}
    if declared:
        merged = _deep_merge(merged, declared)
        layers.append("config.yaml")

    auto = auto_overrides if auto_overrides is not None else load_auto_overrides()
    if auto:
        merged = _deep_merge(merged, auto)
        layers.append("config.strategy_params.yaml")

    return merged, tuple(layers)


def load_swing_params(
    config: dict | None = None,
    auto_overrides: dict | None = None,
) -> SwingParams:
    """加载生效参数。config 省略时走 sim.config.load_config()。"""
    if config is None:
        try:
            from sim.config import load_config

            config = load_config()
        except Exception:
            config = {}

    merged, layers = resolve_params_dict(config, auto_overrides)
    sig = merged["signals"]
    flt = merged["filters"]
    exe = merged["execution"]

    types = exe.get("executable_types") or []
    if isinstance(types, str):
        types = [t.strip() for t in types.split(",") if t.strip()]

    return SwingParams(
        a_ma20_tolerance=float(sig["a_ma20_tolerance"]),
        b_ma10_tolerance=float(sig["b_ma10_tolerance"]),
        max_volume_ratio=float(sig["max_volume_ratio"]),
        quiet_volume_ratio=float(sig["quiet_volume_ratio"]),
        rsi_oversold=float(sig["rsi_oversold"]),
        boll_lower_tolerance=float(sig["boll_lower_tolerance"]),
        e_min_change_pct=float(sig["e_min_change_pct"]),
        f_max_change_pct=float(sig["f_max_change_pct"]),
        min_net_rr=float(flt["min_net_rr"]),
        min_upside_pct=float(flt["min_upside_pct"]),
        min_avg_amp=float(flt["min_avg_amp"]),
        min_score_buy=int(exe["min_score_buy"]),
        executable_types=frozenset(str(t).upper() for t in types),
        stop_loss_pct=float(exe["stop_loss_pct"]),
        take_profit_pct=float(exe["take_profit_pct"]),
        max_positions=int(exe["max_positions"]),
        single_budget=float(exe["single_budget"]),
        raw=merged,
        source_layers=layers,
    )
