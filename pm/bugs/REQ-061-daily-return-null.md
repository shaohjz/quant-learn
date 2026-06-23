# REQ-061: sim_daily_nav 中 account_id=1 的 daily_return 持续为 NULL

## 基本信息
- **需求/Bug ID**: REQ-061
- **标题**: sim_daily_nav 中 daily_return 持续为 NULL
- **状态**: deployed
- **优先级**: P1
- **创建时间**: 2026-06-10
- **修复时间**: 2026-06-20 20:10
- **创建人**: PM Agent
- **指派给**: dev-manager (quant-finance-manager)

## 问题描述
`sim_daily_nav` 表中 `account_id=1` 的 `daily_return` 字段在 2026-06-09 和 2026-06-10 均为 NULL，导致无法正确计算当日收益率。

## 根因分析
1. **`config.yaml` 账户名配置错误**：`accounts.learn.account_name` 被错误配置为 `live_mirror`（应为 `learn`），导致 `detect_account_basis_changes()` 触发 `account_mapping_mismatch` 警告，设置 `pause_return=True`，从而使 `write_daily_nav()` 存储 `daily_return=NULL`。

2. **`snapshot_discontinuity` 误触发 `pause_return`**：现金正常变化（如买入股票导致现金减少）也会触发 `pause_return=True`，这是过于敏感的设计。正常的交易导致的资金变化不应暂停收益率计算。

## 修复方案（2026-06-20 实施）

### 1. 修复 `config.yaml` 配置错误
```yaml
# 修改前
accounts:
  learn:
    account_name: live_mirror  # ❌ 错误

# 修改后
accounts:
  learn:
    account_name: learn  # ✅ 正确
```

同时注释掉废弃的顶层 `account:` 配置块。

### 2. 修改 `write_daily_nav()` 逻辑（`scripts/daily_review.py`）
- **修改前**：当 `pause_daily_return=True` 时存储 `daily_return=NULL`
- **修改后**：始终计算并存储 `daily_return`；当 `pause_return=True` 时，在 `cash_jump_reason` 字段中记录不可比原因

### 3. 修改 `snapshot_discontinuity` 警告逻辑
- **修改前**：`snapshot_discontinuity` 设置 `pause_return=True`
- **修改后**：`snapshot_discontinuity` 设置 `pause_return=False`（正常交易导致的资金变化不应暂停收益率计算）

## 验证结果
```bash
# 修复前（2026-06-19）
SELECT daily_return FROM sim_daily_nav WHERE account_id=1 AND trade_date='2026-06-19';
-- 结果：NULL

# 修复后
SELECT daily_return FROM sim_daily_nav WHERE account_id=1 AND trade_date='2026-06-19';
-- 结果：-0.06855090247263051（正确计算）
```

## 验收标准
1. ✅ `daily_return` 不再为 NULL（即使有 basis warning）
2. ✅ `config.yaml` 账户名配置正确
3. ✅ `snapshot_discontinuity` 不再触发 `pause_return`
4. ✅ `cash_jump_reason` 记录暂停理由（如有）

## 状态历史
- 2026-06-10: 创建 Bug，状态 `open`
- 2026-06-20 20:10: 修复完成，状态 `fixed`
- 2026-06-20 23:05: dev-manager 自测通过，状态 `verified`
- 2026-06-23 18:30: 部署到生产环境（release-agent），状态 `deployed`

## 修改文件
- `config.yaml`：修复 `account_name` 配置
- `scripts/daily_review.py`：`write_daily_nav()` 逻辑修改
