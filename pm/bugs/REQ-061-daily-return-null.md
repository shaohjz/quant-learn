---
id: REQ-061
type: bug
title: 龙旗科技(603341)移动止损已破位但未执行卖出，持仓悬挂
status: verified
priority: P0
created_at: '2026-07-13 20:06:34'
updated_at: '2026-07-14 09:23:51'
assigned_to: quant-dev
work_notes: 2026-07-13 20:04 复盘自动发现并录入
description: '复盘2026-07-13持仓发现：龙旗科技(603341)建仓价39.55，最高价43.69，

  移动止损价40.34（按最高价回撤7.67%计算），当前价40.27已跌破止损价40.34，

  但sim_trades中该标的今日无任何SELL记录，sim_positions仍持有200股且显示浮盈+144。


  问题：

  1. 止损监控/执行链路未对该标的触发卖出（trailing_stop已破位却未成交）

  2. 与REQ-048(止损执行链路Bug)同类问题复发，可能threshold_state无对应armed记录或巡检未覆盖

  3. 当前快照仍显示虚假浮盈，会误导复盘与风险敞口判断


  建议措施：

  1. 立即人工核查龙旗科技是否应止损，如需执行则补单

  2. 排查trailing_stop破位检测逻辑：是否依赖threshold_state记录存在，缺失则漏检

  3. 增加每日巡检：current_price < trailing_stop_price 且 quantity>0 的未止损持仓自动告警'
---

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
