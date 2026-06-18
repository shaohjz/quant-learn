# BUG-006: 数据更新中断 - 缺失数据告警监控缺失

## 基本信息
- **Bug ID**: BUG-006
- **标题**: 数据更新中断 - 缺失数据告警监控
- **状态**: fixed
- **优先级**: P0
- **创建时间**: 2026-06-15 19:40
- **修复时间**: 2026-06-17 01:05
- **创建人**: data-agent
- **指派给**: dev-manager

## 描述
数据更新流程中断时缺少监控告警机制，导致数据过期无法及时发现。2026-06-15 曾发生数据中断，缺失 2026-06-13~15 数据，最后成功更新日期为 2026-06-12。

## 影响
- 收盘结算使用过时价格
- 信号生成基于过期数据
- 可能导致错误交易决策

## 修复方案
1. **新增 `scripts/check_data_freshness.py`**：
   - 检查 `data/*.csv` 是否更新到最近交易日
   - 发现数据过期时自动触发 `backfill_data.py` 补录
   - 补录完成后通过企微 Webhook 发送告警
   - 检查结果写入 `pm/data/YYYY-MM-DD-freshness.json`

2. **集成到 cron**：
   - 每日 16:30 自动执行数据新鲜度检查
   - 非交易时段跳过检查

## 验收标准
1. ✅ `scripts/check_data_freshness.py` 可正常运行
2. ✅ `--check-only` 模式仅检查不修复
3. ✅ 数据过期时自动触发 `backfill_data.py`
4. ✅ 企微告警正常发送
5. ✅ 检查结果正确写入 `pm/data/YYYY-MM-DD-freshness.json`

## 状态历史
- 2026-06-15 19:40: 由 data-agent 创建（原 bugs/BUG-2026-06-15-data-update-interrupted.md）
- 2026-06-17 01:05: 修复完成，新增 `scripts/check_data_freshness.py`，状态 `fixed`
- 2026-06-18 13:03: 部署到生产环境，自测通过，状态 `deployed`

## 附件
- `pm/data/2026-06-17-freshness.json` — 首次检查结果
- `scripts/check_data_freshness.py` — 数据新鲜度检查脚本
