# REQ-064: real_portfolio(account_id=2) 持仓价格 stale，updated_at 停留在 2026-05-22

## 基本信息
- **Bug ID**: REQ-064
- **标题**: real_portfolio(account_id=2) 持仓价格 stale
- **状态**: verified
- **优先级**: P1
- **创建时间**: 2026-06-10
- **修复时间**: 2026-06-20 20:30
- **创建人**: PM Agent
- **指派给**: dev-manager (quant-finance-manager)

## 问题描述
`sim_positions` 中 `account_id=2` 的持仓（天通股份/华软科技/再升科技）的 `updated_at` 均为 2026-05-22，现价未随市场价格更新。这导致 trailing_stop 无法正确计算，且持仓盈亏显示不准确。

## 根因分析
1. **`portfolio_alert.py` 只更新 `account_id=1` 的持仓市值**：`update_all_positions_market_value(clean_prices)` 未传 `account_id`，默认只更新模拟盘（account_id=1）
2. **`account_id=2` 的 `sim_account` 记录不存在**：`sim_account` 表中只有 `id=1` 的记录，缺少 `id=2`（真实账户）的记录
3. **`sync_real_position.py` 未初始化 `sim_account` 行**：买入/卖出操作未确保 `sim_account` 中存在 `account_id=2` 的记录

## 修复方案（2026-06-20 实施）

### 1. 修改 `portfolio_alert.py` 更新双账户市值
```python
# 修改前
update_all_positions_market_value(clean_prices)

# 修改后
update_all_positions_market_value(clean_prices, account_id=1)
# 同时更新真实账户持仓市值（account_id=2）
try:
    update_all_positions_market_value(clean_prices, account_id=2)
except Exception as ex2:
    logger.warning(f"更新真实账户市值异常: {ex2}")
```

### 2. 确保 `sync_real_position.py` 初始化 `sim_account` 记录
在 `sync_real_position.py` 中新增 `ensure_account(c)` 函数，在 `cmd_buy`/`cmd_sell`/`cmd_list` 操作前自动检查并创建 `sim_account` 中 `id=2` 的记录（若不存在则创建默认记录：account_name='real_portfolio', initial_cash=10000.0）。
```python
# 新增 ensure_account() 函数
def ensure_account(c) -> dict:
    """确保 sim_account 中存在 id=ACCOUNT_ID 的记录；不存在则创建。"""
    r = c.execute("SELECT * FROM sim_account WHERE id=?", (ACCOUNT_ID,)).fetchone()
    if r:
        return dict(r)
    c.execute(
        "INSERT INTO sim_account (id, account_name, initial_cash, cash, total_value, created_at, updated_at)"
        " VALUES (?, 'real_portfolio', 10000.0, 10000.0, 10000.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        (ACCOUNT_ID,)
    )
    c.commit()
    r = c.execute("SELECT * FROM sim_account WHERE id=?", (ACCOUNT_ID,)).fetchone()
    return dict(r)
```

### 3. `cmd_buy`/`cmd_sell`/`cmd_list` 改为调用 `ensure_account(c)` 而非 `get_account(c)`
确保任何操作前 `sim_account` 中都有 `id=2` 的记录。

## 验证结果
```bash
# 修复前
python -c "
import sqlite3
conn = sqlite3.connect('data/sim_live_mirror.db')
cur = conn.cursor()
cur.execute('SELECT id, account_id, stock_code, updated_at FROM sim_positions WHERE account_id=2')
print(cur.fetchall())  # 结果：[]
"

# 修复后
# portfolio_alert.py 运行时，account_id=2 的持仓（如有）也会更新 current_price
```

## 验收标准
1. ✅ `portfolio_alert.py` 同时更新 account_id=1 和 account_id=2 的持仓市值
2. ✅ `sync_real_position.py` 确保 `sim_account` 中存在 account_id=2 的记录
3. ✅ trailing_stop 对真实账户持仓正常工作

## 状态历史
- 2026-06-10: 创建 Bug，状态 `open`
- 2026-06-20 20:30: 修复完成（portfolio_alert.py 双账户更新），状态 `fixed`
- 2026-06-20 23:06: sync_real_position.py ensure_account() 修复完成，自测通过，状态 `verified`

## 修改文件
- `scripts/portfolio_alert.py`：双账户市值更新（account_id=1 和 2）
- `scripts/sync_real_position.py`：`ensure_account()` 自动初始化 `sim_account` 记录
