# REQ-002: 完整采样（OHLCV 完整性）

## 基本信息
- **需求 ID**: REQ-002
- **标题**: 完整采样（OHLCV 完整性）
- **状态**: done
- **优先级**: P1
- **创建时间**: 2026-06-09
- **创建人**: PM Agent
- **指派给**: 研发 Agent

## 背景
采样数据缺少完整 OHLCV，导致策略回测不准确。

## 目标
确保从数据源获取的 K 线数据包含完整的 open/high/low/close/volume。

## 详细需求
1. **数据完整性**：
   - `fetch_from_akshare` 返回 open/high/low/close/volume
   - `fetch_from_baostock` 返回完整 OHLCV
   - 数据质量检查：`dropna`、`sort_values`、成交量非负

2. **数据源兜底**：
   - BaoStock 优先，失败后用 AKShare 兜底
   - `fetch_stock_data` 统一入口

## 验收标准
1. ✅ `fetch_from_akshare` 处理完整 OHLCV
2. ✅ `fetch_from_baostock` 作为主力数据源
3. ✅ 数据质量检查：`dropna`、`sort_values`
4. ✅ 统一日期格式为 `pd.to_datetime`

## 相关数据文件
- `scripts/backfill_data.py`

## 状态历史
- 2026-06-09: 创建需求，状态 `pending`
- 2026-06-10: 实现完成，状态 `testing`
- 2026-06-15 17:00: QA 验收通过（测试报告 TEST-2026-06-15-002），状态 `done`
