# BUG-003: 采样数据不足

## 基本信息
- **Bug ID**: BUG-003
- **标题**: 采样数据不足（backfill 从固定日期开始）
- **状态**: verified
- **优先级**: P1
- **创建时间**: 2026-06-09
- **创建人**: PM Agent
- **指派给**: 研发 Agent
- **修复时间**: 2026-06-10

## 描述
`scripts/backfill_data.py` 中的 `backfill_stock` 函数从固定日期开始获取历史数据，而不是从已有数据的最后日期继续，导致重复获取或数据不足。

## 复现步骤
1. 运行 `python scripts/backfill_data.py`
2. 观察数据获取起始日期

## 预期行为
从 CSV 文件的最后日期 + 1 天开始获取新数据。

## 实际行为
从固定日期（如 2020-01-01）开始获取，导致重复。

## 修复方案
修改 `backfill_stock` 函数：
1. 使用 `get_last_date(csv_file)` 获取已有数据最后日期
2. 从 `last_date + 1` 开始获取新数据

## 验证结果
✅ 通过（验证时间：2026-06-15 17:00）

验证步骤：
1. 代码审查 `backfill_stock` 函数，确认使用 `get_last_date`
2. 确认起始日期为 `last_dt + timedelta(days=1)`
3. 确认 `fetch_stock_data` 正确传递 `start_str` 和 `end_str`

## 状态历史
- 2026-06-09: 创建 Bug，状态 `open`
- 2026-06-10: 修复完成，状态 `fixed`
- 2026-06-15 17:00: QA 验证通过，状态 `verified`
