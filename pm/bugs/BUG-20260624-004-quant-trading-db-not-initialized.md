## 基本信息
- **Bug ID**: BUG-20260624-004
- **标题**: quant_trading.db 未正确初始化
- **状态**: fixed
- **严重度**: S2
- **创建时间**: 2026-06-24 19:05
- **创建人**: PM Agent (ops-agent-daily)
- **指派给**: dev-manager

---

## 问题描述

`quant_trading.db`（项目根目录下）仅包含测试表 `ops_test` 和 `_ops_test`，未包含任何业务数据表（如 `trades`, `positions`, `accounts` 等）。

相比之下，`data/sim_live_mirror.db` 包含完整的模拟交易数据（13张表，38笔交易记录）。

---

## 复现步骤

1. 检查 `quant_trading.db` 的表结构：
   ```python
   import sqlite3
   db = sqlite3.connect('quant_trading.db')
   tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
   # 结果: [('ops_test',), ('_ops_test',)]
   ```

---

## 预期行为

`quant_trading.db` 应包含业务数据表，或此文件不应存在（如使用 `sim_live_mirror.db` 作为主数据库）。

---

## 实际行为

- `quant_trading.db` 只有 2 个测试表
- `ops_test` 有 1 行数据，`_ops_test` 为空
- 不清楚此数据库是否仍被任何组件引用

---

## 根本原因分析

可能原因：
1. 初始化脚本从未成功运行
2. 初始化脚本创建了测试表后未继续创建业务表
3. 项目已迁移到 `sim_live_mirror.db`，但 `quant_trading.db` 未被清理

---

## 建议修复

1. 搜索代码中对 `quant_trading.db` 的引用：
   ```bash
   grep -r "quant_trading" .
   ```
2. 如无引用，删除此文件
3. 如有引用，运行正确的初始化脚本

---

## 相关检查

- `data/sim_live_mirror.db`: ✅ 正常，包含完整模拟交易数据
- `data/pm.db`: ✅ 正常，包含 `tasks` 表

---

## 状态跟踪

- [x] 待确认：是否仍引用 `quant_trading.db`
- [x] 待修复：删除或重新初始化
- [x] 待验证：修复后数据库可被正常读写

## 状态历史
- 2026-06-24 19:05: 创建 Bug，状态 `open`
- 2026-06-24 19:20: 开始修复，状态 `in_progress`
- 2026-06-24 19:23: 修复完成，状态 `fixed`

## 修复记录

### 问题分析

1. 搜索代码中对 `quant_trading.db` 的引用：
   - `check_database.py`: 仅用于诊断，不是业务逻辑
   - `_find_buy_records2.py`: 文件不存在（已删除）

2. 结论：`quant_trading.db` 未被任何业务代码引用，可以安全删除

### 实施的修复

1. **删除 `quant_trading.db`**：
   - 文件已删除（`os.remove('quant_trading.db')`）
   - 该文件仅包含测试表，无业务数据

2. **更新 `check_database.py`**：
   - 移除对 `quant_trading.db` 的引用
   - 改为检查所有业务数据库（`sim_live_mirror.db`, `pm.db`）
   - 增强脚本：支持检查多个数据库，输出详细报告

### 验证方法

修复后，运行数据库检查脚本：
```bash
.venv\Scripts\python check_database.py
```

预期输出：
- `sim_live_mirror.db`: ✅ 通过
- `pm.db`: ✅ 通过

### 影响范围

- ✅ 无功能影响（`quant_trading.db` 未被使用）
- ✅ 诊断脚本增强（现在检查所有业务数据库）

---

**巡检报告**: `pm/ops/2026-06-24-ops.md`
