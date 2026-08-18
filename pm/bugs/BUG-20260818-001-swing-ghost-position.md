# BUG-20260818-001: swing 系列清仓逻辑 UPDATE quantity=0 致幽灵持仓残留

## 基本信息
- **Bug ID**: BUG-20260818-001
- **标题**: swing 系列清仓逻辑用 UPDATE SET quantity=0 而非 DELETE，致幽灵持仓残留
- **状态**: fixed
- **优先级**: P1
- **创建时间**: 2026-08-18 20:10
- **修复时间**: 2026-08-18 20:10
- **创建人**: dev-manager (quant-dev-manager)
- **指派给**: dev-manager (quant-dev-manager)

## 描述
TASK-20260718-2003-001（清仓后 DELETE 而非 UPDATE SET quantity=0）在 `sim/engine.py` 与
`scripts/stop_loss_auto.py` 已修复，但同一 bug 类在 swing 波段交易链路仍存在，未闭环：

- `scripts/swing_daily_report.py::sim_sell()` —— 被 `swing_intraday_watch.py` 盘中买入/止损路径复用
- `scripts/swing_auto_trader_v2.py::sell_stock()`
- `scripts/swing_auto_trader.py::sell_stock()`

三处清仓均写 `UPDATE sim_positions SET quantity=0 ...`，导致 `sim_positions` 表残留 quantity=0 幽灵行。

## 影响
- 残留幽灵行污染 `sim_positions` 原始 COUNT / 市值统计（如 swing_trade 账户 COUNT(*) 显示 6 而实际持仓仅 5）
- 当日 601211 国泰海通 SELL_STOP 在 phantom 持仓上成交（`sim_fill ok:true, realized=-479`），写入了无真实持仓基础的成交记录
- 与 PM 任务 #26「清仓后 sim_positions 残留记录未清理」同根因，#26 标记 done 但仅覆盖 engine 路径，未覆盖 swing 脚本

## 修复方案（2026-08-18 实施）
三处清仓逻辑统一改为 `DELETE FROM sim_positions WHERE id=?`（或 `WHERE account_id=? AND stock_code=? AND quantity>0`），对齐 `sim/engine.py` / `stop_loss_auto.py` 的既有规范。

同时清理既有幽灵数据：
- `DELETE FROM sim_positions WHERE quantity<=0` —— 清理 1 条（601211 国泰海通，account_id=3，quantity=0）

## 相关数据文件
- `scripts/swing_daily_report.py`
- `scripts/swing_auto_trader_v2.py`
- `scripts/swing_auto_trader.py`
- `data/sim_live_mirror.db`

## 验收标准
1. ✅ 三处 swing 清仓逻辑改为 DELETE
2. ✅ 幽灵记录（601211）已清理
3. ✅ swing_trade 账户持仓数恢复 5（=MAX_POSITIONS）
4. ✅ `tests/test_swing_intraday_watch.py` 4 passed

## 状态历史
| 时间 | 状态 | 说明 |
|------|------|------|
| 2026-08-18 20:10 | fixed | 修复并清理幽灵数据 |
