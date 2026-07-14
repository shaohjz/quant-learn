# REQ-063 修复报告

## 问题描述

豫能控股(001896) 在 2026-06-02 收盘确认 `take_profit` 阈值触发（`threshold_state.status='armed'`, `close_confirmed_at='2026-06-02'`），但次日（2026-06-03）没有自动执行卖出。最终在 2026-06-10 以止损方式离场，而非止盈。

## 根因分析

`portfolio_alert.py` 中的 `main()` 函数处理实时价格触发的阈值提醒和模拟下单，但**不处理 `threshold_state` 表中 `status='armed'` 的信号的自动执行**。

流程断裂点：
1. 日终检查将 `threshold_state.status` 设为 `armed`，并设置 `close_confirmed_at`
2. **次日应该**：设置 `next_day_confirmed_at`，调用 `execute_trade()` 执行卖出，更新 `status='executed'`
3. **实际**：没有代码执行这个"次日卖出"逻辑 → `armed` 信号永远卡住

`threshold_state` 表中有 3 个 `armed` 信号受此影响：
- id=4: 600330 trend_break (armed since 2026-05-21)
- id=11: 301179 trend_break (armed since 2026-06-02)  
- id=27: 001896 take_profit (armed since 2026-06-02)

## 修复方案

在 `scripts/portfolio_alert.py` 中添加 `process_armed_signals()` 函数：

1. 查询 `threshold_state` 中 `status='armed'` 且 `close_confirmed_at IS NOT NULL` 的记录
2. 如果 `close_confirmed_at < today`（次日已到），执行：
   - 调用 `execute_trade()` 执行卖出
   - 成功后更新 `threshold_state.status='executed'` 并设置 `next_day_confirmed_at`
   - 如果卖出失败是因为"无持仓"（已手动卖出），也标记为 `executed`
3. 用 `output/.armed_flags/{id}_{today}.flag` 文件去重，避免同一信号在同一天被重复执行

调用时机：在 `main()` 中，交易时段内每次运行都检查（开盘前/开盘后都能处理）。

## 测试验证

运行 `scripts/test_armed.py` 测试结果：
- 3 个 `armed` 信号全部被处理
- `threshold_state` 表中对应记录的 `status` 已更新为 `executed`
- `next_day_confirmed_at` 已设置为今天日期

## 修改文件

- `scripts/portfolio_alert.py`：添加 `process_armed_signals()` 函数，在 `main()` 中调用

## 状态

- REQ-063 状态：`open` → `in_progress` → `fixed`
- `threshold_state` 表中所有 `armed` 信号已处理
- 代码已提交并推送至 `origin/master`
