---
id: REQ-005
type: story
title: 'REQ-005: 观察列表K线缩略图'
status: verified
priority: P2
created_at: '2026-05-26 01:38:22'
updated_at: '2026-08-21 01:17:07'
assigned_to: PM-Agent-dev-3
work_notes: '[2026-06-01 10:14:25] claimed by PM-Agent-dev-3

  [2026-06-10 04:12:42] REQ-005 修复完成：/api/portfolio 支持 account_id 参数，总资产计算修正为 cash+实时持仓市值，前端添加账户切换器，支持学习/真实账户切换。请验证仪表盘显示是否正确。

  [2026-08-21 01:17:06] 2026-08-21: 总资产/账户切换已部署，关 testing'
description: Migrated from REQ-005.md
---

# REQ-005: 总资产显示修复

## 基本信息
- **需求 ID**: REQ-005
- **标题**: 总资产显示修复
- **状态**: deployed
- **优先级**: P0
- **创建时间**: 2026-06-10
- **创建人**: PM Agent
- **指派给**: 研发 Agent

## 背景
`sim_account` 表的 `total_value` 字段未正确更新，导致前端/复盘报告显示错误的总资产。

## 目标
确保 `total_value` 在所有相关函数中正确计算和返回。

## 详细需求
1. **DB 字段**：`sim_account` 表有 `total_value` 字段
2. **函数返回**：`get_account()` 返回 `total_value`
3. **计算逻辑**：`daily_settle()` 正确计算 `total_value = cash + market_value`
4. **报告使用**：前端/复盘报告使用正确的 `total_value`

## 验收标准
1. ✅ `sim_account` 表有 `total_value` 字段
2. ✅ `get_account()` 返回 `total_value`
3. ✅ `daily_settle()` 正确计算 `total_value`
4. ✅ `sim_daily_nav` 表记录 `total_value`

## 相关数据文件
- `sim/engine.py`
- `sim/db.py`
- `sim/review.py`

## 状态历史
- 2026-06-10: 创建需求，状态 `pending`
- 2026-06-12: 实现完成，状态 `testing`
- 2026-06-15 17:00: QA 验收通过（测试报告 TEST-2026-06-15-002），状态 `done`
- 2026-06-15 18:37: 部署到 production，状态 `deployed`
- 2026-06-17 18:30: 部署到生产环境，状态 `deployed`

