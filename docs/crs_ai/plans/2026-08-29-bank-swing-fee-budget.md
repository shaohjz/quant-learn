# 银行波段手续费试算修复 + 银行池独立参数 实施计划

<!-- session_id:  -->
<!-- tapd_url:  -->

> **对于代理工作者：** 必需：使用 dev-subagent（如果子代理可用）或 dev-executing 来实施此计划。步骤使用复选框（`- [ ]`）语法进行跟踪。

**目标：** 修复低价股手续费率失真，让银行股专用波段（账户 #4）能选出票，并让银行池拥有独立参数而不影响账户 #3。

**架构：** 三处改动彼此独立、可分别提交与回滚。(1) `swing_auto.scan_stock` 新增可选 `fee_budget`，按真实建仓预算试算费率，不传则完全保持现状，因此账户 #3 零影响；(2) `swing_params` 支持按 section 读取参数，银行池走 `bank_swing_strategy:` 段获得独立的盈亏比门槛与可执行信号类型；(3) `run_scan` 不再静默吞异常。

**技术栈：** Python 3、pytest、pyyaml、`quant_core.swing_params.SwingParams`（frozen dataclass，三层合并）

**背景（2026-08-29 实测，16 只银行股 0 只可买）：**

| 根因 | 证据 |
|---|---|
| 手续费按固定 100 股试算，低价股触发最低佣金 5 元，费率被放大 | 光大银行 3.03 元：100 股费率 **3.35%**，按 8000 元预算实际 **0.18%**，失真 **18.9 倍** |
| `min_net_rr ≥ 1.2` 配合"支撑/阻力取最近均线"，低波动股天然≈1 | 招商银行评分 7、A+B 双信号，upside 0.53% / downside 0.58% → 净 RR 仅 0.26 |
| `executable_types` 只认 A/B | 兴业银行净 RR 3.79（修复费率后 11.96，全场最高）因类型为 C 被弃 |

---

## 文件结构

| 文件 | 职责 | 改动 |
|---|---|---|
| `scripts/swing_auto.py` | 扫描与筛选 | 抽出 `fee_test_shares()`；`scan_stock` 加 `fee_budget` 参数 |
| `scripts/swing_daily_report.py` | 通用波段日报（#3 / #4 共用流程） | 新增 `SCAN_FEE_BUDGET` 模块开关；`run_scan` 传参 + 异常记日志 |
| `quant_core/swing_params.py` | 参数唯一真源 | `resolve_params_dict` / `load_swing_params` 加 `section` 参数 |
| `scripts/bank_swing_daily.py` | 银行 profile | 加载银行独立参数并覆盖 `sdr.PARAMS` 等派生常量 |
| `config.yaml` | 人工声明层 | 新增 `bank_swing_strategy:` 段 |
| `tests/test_swing_fee_budget.py` | 新建 | 费率试算与低价股选股回归 |
| `tests/test_bank_swing_daily.py` | 修改 | 银行独立参数生效的断言 |

**设计约束（必须遵守）：**

1. **账户 #3 行为零变化。** 所有新参数都带默认值，`fee_budget=None` 时走原路径（100 股）。验收方式是改前改后跑同一份池子快照，选股结果逐只一致。
2. **不新增硬编码魔法数。** 银行参数写进 `config.yaml`，走 `swing_params` 既有的三层合并，保持"谁改的一眼可查"。
3. **`config.yaml` 会被 `scripts/daily_recalibrate.py` 精准文本替换回写**，只替换特定股票的 trigger/msg，不会删除其他段——新增段是安全的。`apply_strategy_params.py` 只写 `config.strategy_params.yaml`，不碰 `config.yaml`。
4. **银行段不套用机器自动调参层**（`auto_overrides={}`）。自动调参的证据来自 #3 的样本，不能级联到银行池。

---

## 任务 1: 手续费按真实建仓预算试算

**文件：**
- 修改：`scripts/swing_auto.py:194-199`（新增纯函数）、`scripts/swing_auto.py:342-360`
- 修改：`scripts/swing_daily_report.py:69-71`、`scripts/swing_daily_report.py:316-325`
- 测试：`tests/test_swing_fee_budget.py`（新建）

- [ ] **步骤 1: 写失败测试**

新建 `tests/test_swing_fee_budget.py`：

```python
"""费率试算仓位：低价股不能被最低佣金 5 元系统性误杀。

2026-08-29 实测：光大银行 3.03 元，100 股 = 303 元触发最低佣金，
费率 3.35%；按 8000 元预算（2600 股）实际费率 0.18%，失真 18.9 倍。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import swing_auto as sa  # noqa: E402


def test_default_is_legacy_100_shares():
    """不传 fee_budget 时必须是 100 股——账户 #3 行为零变化的前提。"""
    assert sa.fee_test_shares(3.03, None) == 100
    assert sa.fee_test_shares(39.35, None) == 100


def test_budget_rounds_down_to_lot_of_100():
    assert sa.fee_test_shares(3.03, 8000.0) == 2600
    assert sa.fee_test_shares(39.35, 8000.0) == 200
    assert sa.fee_test_shares(3.03, 10.0) == 100  # 不足 1 手时兜底 100 股


def test_low_price_fee_ratio_collapses_with_budget():
    """低价股按预算试算后，费率必须显著下降。"""
    price, resist = 3.03, 3.06
    legacy = sa.calc_fees(price, resist, 100) / (price * 100)
    budgeted = sa.calc_fees(price, resist, sa.fee_test_shares(price, 8000.0)) / (
        price * sa.fee_test_shares(price, 8000.0)
    )
    assert legacy > 0.03          # 旧算法：>3%
    assert budgeted < 0.005       # 新算法：<0.5%
    assert legacy / budgeted > 10  # 失真一个数量级以上


def test_high_price_stock_barely_changes():
    """高价股不该被这个改动影响——避免误伤 #3 的大票。"""
    price = 39.35
    legacy = sa.calc_fees(price, price * 1.01, 100) / (price * 100)
    budgeted = sa.calc_fees(price, price * 1.01, sa.fee_test_shares(price, 10000.0)) / (
        price * sa.fee_test_shares(price, 10000.0)
    )
    assert abs(legacy - budgeted) < 0.005
```

- [ ] **步骤 2: 运行测试验证失败**

运行：`cd /data/shaohjz/quant-learn && python -m pytest tests/test_swing_fee_budget.py -v`
预期：FAIL —— `AttributeError: module 'swing_auto' has no attribute 'fee_test_shares'`

- [ ] **步骤 3: 写最小实现**

`scripts/swing_auto.py`，在 `calc_fees` 之后新增：

```python
def fee_test_shares(price: float, fee_budget: float | None) -> int:
    """费率试算用的股数。

    历史上固定按 100 股试算。低价股（银行股多在 3~11 元）买 100 股只有几百元，
    必然触发最低佣金 5 元，算出的费率被放大 6~19 倍，净盈亏比被打成负数，
    导致低价股结构性选不出来。

    fee_budget 为空时沿用历史行为（100 股），保证未启用该参数的账户行为不变。
    """
    if fee_budget and price > 0:
        return max(100, int(fee_budget / price / LOT_SIZE) * LOT_SIZE)
    return 100
```

（`LOT_SIZE` 需新增模块常量 `LOT_SIZE = 100`，与 `swing_daily_report.LOT` 对齐。）

`scripts/swing_auto.py:342-360` 改为：

```python
    # 计算手续费影响（按真实建仓预算试算，而非固定 100 股）
    test_shares = fee_test_shares(price, fee_budget)
    fees = calc_fees(price, resist, test_shares)
    fee_ratio = fees / (price * test_shares)

    net_upside = upside - fee_ratio
    net_downside = downside + fee_ratio
    net_rr = net_upside / net_downside if net_downside > 0 else 0

    # 最终筛选
    if net_rr < PARAMS.min_net_rr:
        return None
    if upside < PARAMS.min_upside_pct:
        return None
    if avg_amp < PARAMS.min_avg_amp:
        return None

    # 建议仓位：启用预算时按预算给，否则沿用 1 万元口径
    suggested_budget = fee_budget or 10000.0
    suggested_shares = max(LOT_SIZE, int(suggested_budget / price / LOT_SIZE) * LOT_SIZE)
```

签名改为 `def scan_stock(code, name, fee_budget: float | None = None):`，docstring 补充说明。

- [ ] **步骤 4: 运行测试验证通过**

运行：`cd /data/shaohjz/quant-learn && python -m pytest tests/test_swing_fee_budget.py -v`
预期：4 passed

- [ ] **步骤 5: 接线到 run_scan**

`scripts/swing_daily_report.py:69` 附近新增：

```python
# 费率试算预算。None = 沿用历史的固定 100 股口径（账户 #3 现状）。
# 账户 #4 银行池由 bank_swing_daily 覆盖为 BANK 单票预算。
SCAN_FEE_BUDGET: float | None = None
```

`run_scan` 改为：

```python
def run_scan() -> list[dict]:
    results = []
    for code, name in get_stock_pool():
        try:
            r = scan_stock(code, name, fee_budget=SCAN_FEE_BUDGET)
            if r:
                results.append(r)
        except Exception:
            log.warning("扫描失败，已跳过 %s(%s)", code, name, exc_info=True)
        time.sleep(0.12)
    return results
```

（`except` 补日志是任务 3 的一部分，可在此一并完成。）

- [ ] **步骤 6: 回归——账户 #3 行为必须零变化**

先取改前基线（**在改 swing_auto 之前先跑一次并保存结果**）：

```bash
cd /data/shaohjz/quant-learn && python -m pytest tests/ -q 2>&1 | tail -5
```

预期：全量通过。重点确认 `tests/test_swing_params.py`、`tests/test_bank_swing_daily.py`、`tests/test_swing_daily_report*.py` 均 PASS。

- [ ] **步骤 7: 提交**

```bash
git add scripts/swing_auto.py scripts/swing_daily_report.py tests/test_swing_fee_budget.py
git commit -m "fix(swing): 费率按真实建仓预算试算，修复低价股被最低佣金误杀

低价股买 100 股只有几百元，必然触发最低佣金 5 元，费率被放大 6~19 倍，
净盈亏比被打成负数。新增可选 fee_budget，不传时沿用 100 股口径，
账户 #3 行为零变化。"
```

---

## 任务 2: 银行池独立参数段

**文件：**
- 修改：`quant_core/swing_params.py:117-180`
- 修改：`scripts/bank_swing_daily.py:26-48`
- 修改：`config.yaml`（`swing_strategy:` 段之后新增）
- 测试：`tests/test_bank_swing_daily.py`

- [ ] **步骤 1: 写失败测试**

`tests/test_bank_swing_daily.py` 末尾追加：

```python
def test_bank_params_come_from_bank_section(monkeypatch, tmp_path):
    """银行池必须读 bank_swing_strategy: 段，而不是 #3 的 swing_strategy:。"""
    import yaml
    import swing_daily_report as sdr
    from scripts.bank_swing_daily import apply_bank_profile

    cfg = {
        "swing_strategy": {"filters": {"min_net_rr": 1.2},
                           "execution": {"executable_types": ["A", "B"], "single_budget": 10000.0}},
        "bank_swing_strategy": {"filters": {"min_net_rr": 1.0},
                                "execution": {"executable_types": ["A", "B", "C", "D"],
                                             "single_budget": 8000.0}},
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    from sim import config as sim_config
    monkeypatch.setattr(sim_config, "load_config", lambda: cfg)
    monkeypatch.setenv("QUANT_ARTIFACT_ROOT", str(tmp_path))

    apply_bank_profile()

    assert sdr.PARAMS.min_net_rr == 1.0
    assert sdr.PARAMS.single_budget == 8000.0
    assert sdr.EXECUTABLE_TYPES == {"A", "B", "C", "D"}
    assert sdr.SCAN_FEE_BUDGET == 8000.0
```

- [ ] **步骤 2: 运行测试验证失败**

运行：`cd /data/shaohjz/quant-learn && python -m pytest tests/test_bank_swing_daily.py -v`
预期：FAIL（`sdr.PARAMS.min_net_rr` 仍为 1.2，`SCAN_FEE_BUDGET` 属性不存在）

- [ ] **步骤 3: 实现 section 参数**

`quant_core/swing_params.py`：

```python
def resolve_params_dict(
    config: dict | None = None,
    auto_overrides: dict | None = None,
    section: str = "swing_strategy",
) -> tuple[dict, tuple[str, ...]]:
    """按三层优先级合并，返回 (参数树, 生效层名)。

    section 让不同账户池（如 bank_swing_strategy）拥有各自的人工声明段，
    互不干扰。
    """
    layers = ["defaults"]
    merged = copy.deepcopy(DEFAULTS)

    declared = ((config or {}).get(section) or {}) if config else {}
    if declared:
        merged = _deep_merge(merged, declared)
        layers.append(f"config.yaml:{section}")
    ...
```

`load_swing_params` 同步加 `section: str = "swing_strategy"` 并透传。

- [ ] **步骤 4: 银行 profile 接线**

`scripts/bank_swing_daily.py`：

```python
BANK_SECTION = "bank_swing_strategy"

def apply_bank_profile() -> None:
    ...
    # 银行独立参数段。不套用机器自动调参层——那层的证据来自 #3 的样本，
    # 级联到银行池会让自动调参同时影响两个结论不同的账户。
    bank_params = load_swing_params(section=BANK_SECTION, auto_overrides={})
    sdr.PARAMS = bank_params
    sdr.MIN_SCORE_BUY = bank_params.min_score_buy
    sdr.EXECUTABLE_TYPES = set(bank_params.executable_types)
    sdr.STOP_LOSS_PCT = bank_params.stop_loss_pct
    sdr.TAKE_PROFIT_PCT = bank_params.take_profit_pct
    sdr.MAX_POSITIONS = bank_params.max_positions
    sdr.SINGLE_BUDGET = bank_params.single_budget
    sdr.SCAN_FEE_BUDGET = bank_params.single_budget
    ...
```

删除 `BANK_MAX_POSITIONS` / `BANK_SINGLE_BUDGET` 两个硬编码常量（改为配置驱动）。

- [ ] **步骤 5: config.yaml 加银行段**

在 `swing_strategy:` 段之后新增（**保持 LF 行尾，与文件现状一致**）：

```yaml
# 账户 #4 银行股专用波段的独立参数。留空则沿用上面 swing_strategy 的默认值。
# 银行股波动小、股价低（3~11 元），通用参数下结构性选不出票（2026-08-29 实测 16 只 0 只可买）。
bank_swing_strategy:
  filters:
    # 通用为 1.2。银行股回踩时支撑/阻力都紧贴现价，比值天然≈1，
    # 1.2 会把所有回踩信号一律挡在门外。
    min_net_rr: 1.0
  execution:
    # 通用只认 A/B（缩量回踩 MA20/MA10）。布林下轨(C) 与 RSI超卖(D)
    # 对低波动银行股是有效的入场信号，放开后可覆盖更多机会。
    executable_types: ["A", "B", "C", "D"]
    max_positions: 3
    single_budget: 8000.0
```

- [ ] **步骤 6: 运行测试验证通过**

运行：`cd /data/shaohjz/quant-learn && python -m pytest tests/ -q 2>&1 | tail -8`
预期：全量 PASS

- [ ] **步骤 7: 提交**

```bash
git add quant_core/swing_params.py scripts/bank_swing_daily.py config.yaml tests/test_bank_swing_daily.py
git commit -m "feat(swing): 银行池独立参数段 bank_swing_strategy

银行股波动小、股价低，通用参数下 16 只 0 只可买。
支持 swing_params 按 section 读取，银行池获得独立的盈亏比门槛与
可执行信号类型。未配置该段时行为与之前完全一致。"
```

---

## 任务 3: run_scan 异常不再静默吞掉

**文件：** `scripts/swing_daily_report.py:316-325`
（已在任务 1 步骤 5 一并完成；若任务 1 已覆盖，此任务只需补测试与提交。）

- [ ] **步骤 1: 补测试**

`tests/test_swing_fee_budget.py` 追加：

```python
def test_run_scan_logs_instead_of_swallowing(monkeypatch, caplog):
    """扫描单只股票抛异常时必须留下日志，不能静默 pass。"""
    import logging
    import swing_daily_report as sdr

    monkeypatch.setattr(sdr, "get_stock_pool", lambda: [("sh600000", "浦发银行")])
    monkeypatch.setattr(sdr, "scan_stock", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(sdr.time, "sleep", lambda *_: None)

    with caplog.at_level(logging.WARNING, logger="swing_daily"):
        out = sdr.run_scan()

    assert out == []
    assert "浦发银行" in caplog.text
```

- [ ] **步骤 2: 运行测试验证通过**

运行：`cd /data/shaohjz/quant-learn && python -m pytest tests/test_swing_fee_budget.py -v`
预期：PASS

- [ ] **步骤 3: 提交**

```bash
git add tests/test_swing_fee_budget.py scripts/swing_daily_report.py
git commit -m "fix(swing): run_scan 异常记日志，不再静默 pass"
```

---

## 任务 4: 实盘验证与回归

**文件：** 无代码改动，仅验证与记录。

- [ ] **步骤 1: 验证银行池改后可选出票**

```bash
cd /data/shaohjz/quant-learn && python scripts/bank_swing_daily.py --no-trade --no-push
```

预期：不再是"空仓观望 / 无强买点"。记录改动前后可买只数对比（改前 0 只）。

- [ ] **步骤 2: 回归账户 #3 零影响**

```bash
cd /data/shaohjz/quant-learn && python -m pytest tests/ -q 2>&1 | tail -8
```

并用同一份 `output/swing_pool/latest.json` 对比改前改后的扫描结果逐只一致（`SCAN_FEE_BUDGET=None` 走原路径）。

- [ ] **步骤 3: 记录结论**

在 `pm/strategy_review/2026-08-29-bank-swing-fix.md` 记录：改前 0 只 → 改后 N 只、#3 回归无差异、后续待评估项（是否给 #3 也启用 fee_budget，需先回测）。

- [ ] **步骤 4: 提交并推送**

```bash
git add pm/strategy_review/2026-08-29-bank-swing-fix.md
git commit -m "docs: 记录银行波段费率修复的改前后对比"
git push origin master
```

---

## 待办（不在本次范围，需回测后再定）

1. **账户 #3 是否也启用 `fee_budget`** —— #3 池里同样有低价股（5 元档），费率失真同样存在。但启用会改变 #3 的选股结果，而 #3 当前 5 只满仓在跑，必须先回测对比再决定。
2. **`min_net_rr` 的算法本身** —— "支撑/阻力取最近均线"对任何低波动标的都会把比值压到≈1。若要长期支持低波动池，应考虑改用 ATR 或固定百分比止损来算 downside，而非最近均线。
3. **`max_volume_ratio=0.8` 在银行股上偏严** —— 08-28 有 6 只因量比 0.81~0.93 差一点点被挡，可考虑银行段单独放宽到 0.95（需样本验证）。
