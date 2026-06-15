# BUG-005: 双账户不一致

## 基本信息
- **Bug ID**: BUG-005
- **标题**: 双账户不一致（config 与 DB 映射混乱）
- **状态**: deployed
- **优先级**: P0
- **创建时间**: 2026-06-10
- **创建人**: PM Agent
- **指派给**: 研发 Agent
- **修复时间**: 2026-06-12

## 描述
`config.yaml` 中定义了多个账户（`learn`、`real`），但 `sim/engine.py` 中的 `SimEngine` 未正确区分账户，导致数据写入错误的账户。

## 复现步骤
1. 查看 `config.yaml` 中的 `accounts` 配置
2. 运行 `SimEngine(account_id=2)` 操作实盘账户
3. 检查 `sim_account` 表数据

## 预期行为
`SimEngine(account_id=2)` 操作 `sim_account` 中 id=2 的记录。

## 实际行为
所有操作默认使用 `account_id=1`，忽略 `config.yaml` 中的多账户配置。

## 修复方案
1. `SimEngine.__init__` 接受 `account_id` 参数
2. 所有 DB 操作使用 `self.account_id` 而非硬编码的 1
3. `sim.config.get_account_config()` 正确读取 `accounts.<name>.initial_cash`

## 验证结果
✅ 通过（验证时间：2026-06-15 17:00）

验证步骤：
1. `SimEngine` 支持 `account_id` 参数（通过 `__init__` 签名验证）
2. `sim.config.get_account_config(1)` 返回正确的 `initial_cash=100000.0`
3. `sim_account` 表有正确的账户记录

## 状态历史
- 2026-06-10: 创建 Bug，状态 `open`
- 2026-06-12: 修复完成，状态 `fixed`
- 2026-06-15 17:00: QA 验证通过，状态 `verified`
- 2026-06-15 18:37: 部署到 production，状态 `deployed`
