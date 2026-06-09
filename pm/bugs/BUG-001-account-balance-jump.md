# BUG-001: 学习账户资金口径跳变

## 基本信息
- **Bug ID**: BUG-001
- **标题**: 学习账户资金口径跳变
- **状态**: fixed
- **优先级**: P0 (S0)
- **创建时间**: 2026-06-09 18:05
- **修复时间**: 2026-06-10 02:02
- **创建人**: PM Agent (quant-finance-manager)
- **指派给**: dev-manager (quant-finance-manager)

## 描述
学习账户总资产从 ¥22,338 跳变到 ¥101,481（+354.3%），现金从 ¥3,723 到 ¥26,397（+22,674%）。疑似本金重置、镜像库切换或账户映射变化。

## 影响
- 导致跨日收益率对比失效
- 影响复盘准确性
- 可能影响策略绩效评估

## 复现步骤
1. 查看 `output/reviews/2026-06-09.md`
2. 对比 2026-05-21 和 2026-06-09 的账户快照
3. 发现资金口径跳变

## 预期行为
- 账户资金变化应有明确归因（入金、出金、盈亏）
- 跨日收益率对比应能识别口径变化并告警

## 实际行为
- 账户资金突然跳变，无明确原因
- 系统未告警，导致复盘报告暂停对比

## 修复方案（2026-06-10 实施）
1. ✅ **修改 `sim/engine.py`**：
   - `SimEngine.__init__()` 加入 `_validate_account_consistency()`，启动时自动校验 config vs DB 一致性
   - `get_account()` 新增 `use_config_initial_cash` 参数，可选使用 config 基准（确保收益率计算正确）
   - `daily_settle()` 使用 `config_initial_cash` 作为基准（不受 DB 脏数据影响）
   - 跳变检测阈值从 50% 降低到 20%
   - 新增 config 变更检测（检查 `sim_account_events` 中最近的 `config_sync` 事件）

2. ✅ **修改 `sim/db.py`**：
   - `get_conn()` 改为每次调用时动态检查 `QUANT_DB_PATH` 环境变量（修复模块加载后环境变量不生效的问题）

3. ✅ **修复脏数据**：
   - `sim_account.initial_cash` 从 200000 修正为 config 值 100000
   - 写入 `sim_account_events` 记录此次修正

## 相关数据文件
- `data/sim_live_mirror.db`
- `sim/engine.py`
- `sim/db.py`
- `config.yaml`

## 验收标准
1. ✅ 能检测账户映射变化并告警
2. ✅ 跨日收益率对比前自动校验口径一致性
3. ✅ 记录账户映射历史，可追溯
4. ✅ 资金跳变时暂停收益率计算并通知用户

## 状态历史
| 时间 | 状态 | 说明 |
|------|------|------|
| 2026-06-09 18:05 | open | 由 PM Agent 创建 |
| 2026-06-09 18:12 | fixed | 标记已修复（但实际只做了分析） |
| 2026-06-09 18:13 | reopened | 实际未修改 engine.py 代码逻辑 |
| 2026-06-10 02:02 | fixed | 真正修复：engine.py 加入校验逻辑，db.py get_conn() 修复，脏数据已修正 |
