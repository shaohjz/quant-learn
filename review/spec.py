"""review/spec.py — 策略真源抽取。

背景：策略参数散落在 6 个脚本的硬编码常量和 config.yaml 的多个段落里。
README 里手写的描述已经和代码对不上（写「池子稳定蓝筹 ≈44」，实际是动态池 ≤50；
写「#1 执行器是 threshold_strategy」，实际是 sim_executor）。手写文档必然漂移。

所以策略说明书不手写，每天从代码和配置里把真实生效值抽出来再渲染。
附带两个能力：

1. 同一个逻辑参数在多处定义时（止损 5% 在 swing_daily_report 和
   swing_intraday_watch 各写一遍），值不一致会被判为 conflict —— 这是
   「改了一个忘了另一个」的经典事故，靠人 review 抓不住。
2. spec_hash 变化即代表策略被改过，可用于检测无记录的静默改参。

抽取用 AST 静态解析，不 import 交易脚本：那些模块在 import 时会建目录、
读配置、解析数据库路径，复盘进程不该有这些副作用。
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 参数分组，决定说明书里的章节顺序
GROUPS = {
    "universe": "选股范围",
    "entry": "买入条件",
    "exit": "卖出条件",
    "sizing": "仓位与资金",
    "risk": "风控闸门",
    "cost": "交易成本",
}

_MISSING = object()


@dataclass(frozen=True)
class ParamRef:
    """参数的一个定义位置。

    kind="module" 时 location 是 py 文件相对路径、symbol 是模块级常量名；
    kind="config" 时 location 是 yaml 文件名、symbol 是点分路径。
    """

    kind: str
    location: str
    symbol: str

    def __str__(self) -> str:
        return f"{self.location}:{self.symbol}"


@dataclass
class ResolvedRef:
    ref: ParamRef
    value: Any
    found: bool

    def to_dict(self) -> dict:
        return {"source": str(self.ref), "value": _jsonable(self.value), "found": self.found}


@dataclass
class Param:
    key: str
    label: str
    group: str
    refs: list[ResolvedRef] = field(default_factory=list)
    unit: str = ""
    note: str = ""

    @property
    def value(self) -> Any:
        for r in self.refs:
            if r.found:
                return r.value
        return None

    @property
    def found(self) -> bool:
        return any(r.found for r in self.refs)

    @property
    def conflict(self) -> bool:
        """多个来源都有值但不相等 —— 漂移事故。"""
        values = [_jsonable(r.value) for r in self.refs if r.found]
        if len(values) < 2:
            return False
        first = json.dumps(values[0], sort_keys=True, ensure_ascii=False)
        return any(json.dumps(v, sort_keys=True, ensure_ascii=False) != first for v in values[1:])

    def display(self) -> str:
        v = self.value
        if v is None:
            return "（未取到）"
        if isinstance(v, bool):
            return "开" if v else "关"
        if isinstance(v, (set, frozenset, list, tuple)):
            return "/".join(sorted(str(x) for x in v))
        if isinstance(v, (int, float)):
            # config 里百分比单位不统一：stop_loss_pct 存 -0.08，block_add_to_loser_pct 存 -3.0。
            # frac 表示值是小数比例，% 表示值本身已是百分数。
            if self.unit == "frac":
                return f"{v * 100:g}%"
            if self.unit == "%":
                return f"{v:g}%"
            if self.unit == "元":
                if abs(v) >= 1e8:
                    return f"{v / 1e8:g} 亿"
                if abs(v) >= 10000:
                    return f"{v / 10000:g} 万"
            return f"{v:g}{self.unit}"
        return str(v)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "group": self.group,
            "value": _jsonable(self.value),
            "display": self.display(),
            "unit": self.unit,
            "note": self.note,
            "found": self.found,
            "conflict": self.conflict,
            "refs": [r.to_dict() for r in self.refs],
        }


@dataclass
class StrategySpec:
    strategy_id: str
    account_id: int
    name: str
    headline: str
    params: list[Param] = field(default_factory=list)

    def get(self, key: str) -> Param | None:
        return next((p for p in self.params if p.key == key), None)

    def value(self, key: str, default: Any = None) -> Any:
        p = self.get(key)
        return default if p is None or not p.found else p.value

    def conflicts(self) -> list[Param]:
        return [p for p in self.params if p.conflict]

    def missing(self) -> list[Param]:
        return [p for p in self.params if not p.found]

    def spec_hash(self) -> str:
        payload = {p.key: _jsonable(p.value) for p in self.params}
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "account_id": self.account_id,
            "name": self.name,
            "headline": self.headline,
            "spec_hash": self.spec_hash(),
            "params": [p.to_dict() for p in self.params],
            "conflicts": [p.key for p in self.conflicts()],
            "missing": [p.key for p in self.missing()],
        }


def _jsonable(v: Any) -> Any:
    if isinstance(v, (set, frozenset)):
        return sorted(str(x) for x in v)
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)  # YAML 会把裸日期解析成 date，config 里的 watchlist 就有


# ─────────────────────────── 抽取器 ───────────────────────────


def read_module_constants(path: Path) -> dict[str, Any]:
    """静态读取 py 文件的模块级字面量常量。

    只认能被 ast.literal_eval 求值的赋值，函数体内和 if/try 分支内的一律跳过 ——
    宁可报「未取到」，也不能猜错一个止损参数。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return {}

    out: dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if node.value is None:
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError, TypeError):
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                out[t.id] = value
    return out


def read_config_path(cfg: dict, dotted: str) -> Any:
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


class SpecExtractor:
    """按 ParamRef 声明去代码/配置里取值，带模块解析缓存。"""

    def __init__(self, root: Path | None = None, config: dict | None = None):
        self.root = root or PROJECT_ROOT
        self._modules: dict[str, dict[str, Any]] = {}
        self._config = config if config is not None else _load_config(self.root)
        self._params_cache: dict | None = None

    def _module(self, rel: str) -> dict[str, Any]:
        if rel not in self._modules:
            self._modules[rel] = read_module_constants(self.root / rel)
        return self._modules[rel]

    def resolve(self, ref: ParamRef) -> ResolvedRef:
        if ref.kind == "module":
            consts = self._module(ref.location)
            if ref.symbol in consts:
                return ResolvedRef(ref, consts[ref.symbol], True)
            return ResolvedRef(ref, None, False)
        if ref.kind == "config":
            val = read_config_path(self._config, ref.symbol)
            if val is _MISSING:
                return ResolvedRef(ref, None, False)
            return ResolvedRef(ref, val, True)
        if ref.kind == "params":
            val = read_config_path(self._swing_params(), ref.symbol)
            if val is _MISSING:
                return ResolvedRef(ref, None, False)
            return ResolvedRef(ref, val, True)
        return ResolvedRef(ref, None, False)

    def _swing_params(self) -> dict:
        """波段参数真源的**生效值**（含 config 与自动调参覆盖层）。

        读生效值而不是 DEFAULTS，才能发现「YAML 改了参数但脚本常量没跟上」。

        该模块尚未落地时返回空 dict：对应的 ParamRef 记为 found=False，
        参数照旧从脚本常量取，不影响复盘；一旦模块就位，partial_migration
        规则会自动开始守护迁移。
        """
        if self._params_cache is None:
            try:
                from quant_core.swing_params import load_swing_params

                self._params_cache = load_swing_params().raw or {}
            except Exception:
                self._params_cache = {}
        return self._params_cache

    def param(self, key: str, label: str, group: str, refs: list[ParamRef], unit: str = "", note: str = "") -> Param:
        return Param(key=key, label=label, group=group, unit=unit, note=note,
                     refs=[self.resolve(r) for r in refs])


def _load_config(root: Path) -> dict:
    """读 config.yaml 并叠加 config.local.yaml，与 sim.config 同口径但不引入其副作用。"""
    try:
        import yaml
    except ImportError:
        return {}
    cfg: dict = {}
    for name in ("config.yaml", "config.local.yaml"):
        p = root / name
        if not p.exists():
            continue
        try:
            loaded = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if isinstance(loaded, dict):
            cfg = _deep_merge(cfg, loaded)
    return cfg


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# ─────────────────────── 策略参数注册表 ───────────────────────
#
# 这张表是「策略有哪些旋钮」的唯一声明。新增参数在这里加一行，
# 说明书、漂移检测、诊断规则会同时生效。

M = "module"
C = "config"
P = "params"  # quant_core/swing_params.py 的生效值（含 YAML 覆盖层）

_SWING_DAILY = "scripts/swing_daily_report.py"
_SWING_INTRADAY = "scripts/swing_intraday_watch.py"
_SWING_POOL = "scripts/swing_pool_builder.py"
_SWING_AUTO = "scripts/swing_auto.py"
_SIM_EXEC = "scripts/sim_executor.py"


def build_swing_spec(ex: SpecExtractor) -> StrategySpec:
    """#3 波段仓：动态稳定池里找缩量回踩，固定百分比止损止盈。"""
    p = ex.param
    params = [
        p("pool_max", "池子上限", "universe", [ParamRef(M, _SWING_POOL, "DEFAULT_MAX_POOL")], unit="只"),
        p("pool_min_score", "入池稳定分下限", "universe", [ParamRef(M, _SWING_POOL, "DEFAULT_MIN_SCORE")]),
        p("pool_min_amount", "最小成交额", "universe", [ParamRef(M, _SWING_POOL, "MIN_AMOUNT")], unit="元"),
        p("pool_price_floor", "股价下限", "universe", [ParamRef(M, _SWING_POOL, "MIN_PRICE")], unit="元"),
        p("pool_price_cap", "股价上限", "universe", [ParamRef(M, _SWING_POOL, "MAX_PRICE")], unit="元"),
        p("pool_atr_min", "ATR 下限", "universe", [ParamRef(M, _SWING_POOL, "ATR_MIN")]),
        p("pool_atr_max", "ATR 上限", "universe", [ParamRef(M, _SWING_POOL, "ATR_MAX")]),
        p("pool_max_amp", "日均振幅上限", "universe", [ParamRef(M, _SWING_POOL, "MAX_AVG_AMP")]),
        p("pool_max_drop_5d", "5 日跌幅下限", "universe", [ParamRef(M, _SWING_POOL, "MAX_DROP_5D")]),

        p("entry_types", "可成交信号类型", "entry",
          [ParamRef(P, "swing_params", "execution.executable_types"),
           ParamRef(M, _SWING_DAILY, "EXECUTABLE_TYPES"), ParamRef(M, _SWING_INTRADAY, "EXECUTABLE")],
          note="A=缩量回踩MA20 B=缩量回踩MA10；C/D/E/F 只观察"),
        p("entry_min_score", "信号分下限", "entry",
          [ParamRef(P, "swing_params", "execution.min_score_buy"),
           ParamRef(M, _SWING_DAILY, "MIN_SCORE_BUY"), ParamRef(M, _SWING_INTRADAY, "DEFAULT_MIN_SCORE")]),
        p("entry_min_net_rr", "净盈亏比下限", "entry",
          [ParamRef(P, "swing_params", "filters.min_net_rr"), ParamRef(M, _SWING_AUTO, "MIN_NET_RR")]),
        p("entry_min_upside", "预期涨幅下限", "entry",
          [ParamRef(P, "swing_params", "filters.min_upside_pct"), ParamRef(M, _SWING_AUTO, "MIN_UPSIDE")],
          unit="frac"),
        p("entry_min_amp", "个股活性下限", "entry",
          [ParamRef(P, "swing_params", "filters.min_avg_amp"), ParamRef(M, _SWING_AUTO, "MIN_AVG_AMP")],
          note="日均振幅，太死的票不做"),

        p("stop_loss_pct", "止损", "exit",
          [ParamRef(P, "swing_params", "execution.stop_loss_pct"),
           ParamRef(M, _SWING_DAILY, "STOP_LOSS_PCT"), ParamRef(M, _SWING_INTRADAY, "STOP_LOSS_PCT")], unit="frac"),
        p("take_profit_pct", "止盈", "exit",
          [ParamRef(P, "swing_params", "execution.take_profit_pct"),
           ParamRef(M, _SWING_DAILY, "TAKE_PROFIT_PCT"), ParamRef(M, _SWING_INTRADAY, "TAKE_PROFIT_PCT")],
          unit="frac"),

        p("max_positions", "最大持仓数", "sizing",
          [ParamRef(P, "swing_params", "execution.max_positions"),
           ParamRef(M, _SWING_DAILY, "MAX_POSITIONS")], unit="只"),
        p("single_budget", "单笔预算", "sizing",
          [ParamRef(P, "swing_params", "execution.single_budget"),
           ParamRef(M, _SWING_DAILY, "SINGLE_BUDGET")], unit="元"),
        p("initial_cash", "起始资金", "sizing", [ParamRef(C, "config.yaml", "accounts.swing.initial_cash")], unit="元"),
        p("auto_trade", "自动成交", "sizing", [ParamRef(C, "config.yaml", "accounts.swing.auto_trade")],
          note="false=只给挂单建议"),

        p("commission_rate", "佣金率", "cost", [ParamRef(C, "config.yaml", "fees.commission_rate")]),
        p("stamp_tax_rate", "印花税率", "cost", [ParamRef(C, "config.yaml", "fees.stamp_tax_rate")]),
    ]
    return StrategySpec(
        strategy_id="swing",
        account_id=3,
        name="#3 波段仓",
        headline="沪深300+中证500 里挑稳定池 → 缩量回踩 MA10/MA20 买入 → 固定 5% 止损 / 8% 止盈",
        params=params,
    )


def build_learn_spec(ex: SpecExtractor) -> StrategySpec:
    """#1 学习仓：手工观察池按 MA 阈值买，config 风控闸门管出场。"""
    p = ex.param
    params = [
        p("watchlist_size", "观察池规模", "universe", [ParamRef(C, "config.yaml", "watchlist.user_manual")],
          note="盘前 daily_recalibrate 重算每只的 buy_zone/trend_break"),

        p("buy_strong_enabled", "强买通道", "entry", [ParamRef(C, "config.yaml", "risk.buy_strong_enabled")],
          note="关闭时只走 buy_zone"),
        p("max_daily_new_positions", "每日新开仓上限", "entry",
          [ParamRef(C, "config.yaml", "risk.max_daily_new_positions")], unit="笔"),
        p("block_add_to_loser_pct", "浮亏禁加仓线", "entry",
          [ParamRef(C, "config.yaml", "risk.block_add_to_loser_pct")], unit="%"),
        p("market_panic_drop_pct", "大盘弱势禁买线", "entry",
          [ParamRef(C, "config.yaml", "risk.market_panic_index_drop_pct")], unit="%"),

        p("stop_loss_pct", "硬止损", "exit", [ParamRef(C, "config.yaml", "risk.stop_loss_pct")], unit="frac"),
        p("take_profit_pct", "止盈线", "exit", [ParamRef(C, "config.yaml", "risk.take_profit_pct")], unit="frac"),
        p("take_profit_mode", "止盈方式", "exit", [ParamRef(C, "config.yaml", "risk.take_profit_mode")],
          note="half=首次止盈卖一半"),
        p("trailing_mode", "跟踪止损", "exit", [ParamRef(C, "config.yaml", "risk.trailing.mode")]),
        p("trailing_activate_pct", "跟踪启动浮盈", "exit",
          [ParamRef(C, "config.yaml", "risk.trailing.activate_profit_pct")], unit="%"),

        p("single_budget", "单笔预算", "sizing", [ParamRef(M, _SIM_EXEC, "DEFAULT_BUY_BUDGET")], unit="元"),
        p("max_total_positions", "最大持仓数", "sizing", [ParamRef(C, "config.yaml", "risk.max_total_positions")],
          unit="只"),
        p("max_position_pct", "单票市值上限", "sizing", [ParamRef(C, "config.yaml", "risk.max_position_pct")],
          unit="frac"),
        p("initial_cash", "起始资金", "sizing", [ParamRef(C, "config.yaml", "accounts.learn.initial_cash")],
          unit="元"),
        p("auto_trade", "自动成交", "sizing", [ParamRef(C, "config.yaml", "accounts.learn.auto_trade")]),

        p("max_industry_pct", "单行业上限", "risk", [ParamRef(C, "config.yaml", "risk.max_industry_pct")],
          unit="frac"),
        p("max_daily_trades", "单日成交上限", "risk", [ParamRef(C, "config.yaml", "risk.max_daily_trades")], unit="笔"),

        p("commission_rate", "佣金率", "cost", [ParamRef(C, "config.yaml", "fees.commission_rate")]),
        p("stamp_tax_rate", "印花税率", "cost", [ParamRef(C, "config.yaml", "fees.stamp_tax_rate")]),
    ]
    spec = StrategySpec(
        strategy_id="learn",
        account_id=1,
        name="#1 学习仓",
        headline="手工观察池按 MA10 买区试探建仓 → config 风控闸门 + 半仓止盈 / -8% 硬止损",
        params=params,
    )
    # watchlist 原始值是整份观察池，说明书只关心「启用了几只」
    wl = spec.get("watchlist_size")
    if wl and wl.found:
        wl.refs[0].value = _count_enabled(wl.value)
        wl.unit = "只"
    return spec


def _count_enabled(watchlist: Any) -> int:
    """统计观察池中启用的标的数。user_manual 是 code → 配置的 dict。"""
    if isinstance(watchlist, dict):
        items: list = list(watchlist.values())
    elif isinstance(watchlist, list):
        items = list(watchlist)
    else:
        return 0
    return sum(1 for it in items if not isinstance(it, dict) or it.get("enabled", True))


def load_specs(root: Path | None = None, config: dict | None = None) -> list[StrategySpec]:
    ex = SpecExtractor(root=root, config=config)
    return [build_swing_spec(ex), build_learn_spec(ex)]


def render_markdown(specs: list[StrategySpec]) -> str:
    """生成人读的策略说明书。这份文件是自动产物，不要手改。"""
    lines = [
        "# 当前交易策略说明书",
        "",
        "> 本文由 `scripts/strategy_review.py --write-spec` 从**代码和配置里抽取**生成，不要手改。",
        "> 想改策略请改下表「取自」列指向的位置，重跑复盘后本文会自动跟上。",
        "",
    ]
    for spec in specs:
        lines += [
            f"## {spec.name}（account_id={spec.account_id}） `spec_hash={spec.spec_hash()}`",
            "",
            f"**{spec.headline}**",
            "",
        ]
        if spec.conflicts():
            lines.append("> ⚠️ **参数冲突**：以下参数在多处定义且值不一致，改动很可能只改了一半。")
            lines.append("")
            for p in spec.conflicts():
                detail = "；".join(f"{r.ref} = {_jsonable(r.value)}" for r in p.refs if r.found)
                lines.append(f"> - `{p.key}`（{p.label}）：{detail}")
            lines.append("")

        for gkey, gname in GROUPS.items():
            rows = [p for p in spec.params if p.group == gkey]
            if not rows:
                continue
            lines += [f"### {gname}", "", "| 参数 | 当前值 | 取自 | 说明 |", "|------|-------|------|------|"]
            for p in rows:
                src = "<br>".join(f"`{r.ref}`" for r in p.refs) or "—"
                flag = " ⚠️冲突" if p.conflict else ("" if p.found else " ❌未取到")
                lines.append(f"| {p.label}{flag} | **{p.display()}** | {src} | {p.note} |")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
