import sqlite3
from datetime import datetime, date

conn = sqlite3.connect('data/pm.db')
cursor = conn.cursor()

now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# 需求单1: 账户数据一致性问题
task1 = (
    'REQ-070',
    'bug',
    '模拟盘账户总市值(total_value)与现金+持仓市值不一致',
    '每日复盘发现 sim_account.total_value(9800) != cash(9000) + SUM(sim_positions.market_value)(1106) = 10106，差异306元。\n\n可能原因：\n1. total_value字段更新逻辑有bug，未正确刷新\n2. 有资金流出（如手续费、转账）未记录到 sim_account_events\n3. 持仓市值计算与账户总市值计算用不同价格（当前价vs成本价）\n\n影响：所有依赖total_value的策略判断（如仓位管理、止损触发）可能不准确。\n建议修复 sim_account 的 total_value 更新触发器/逻辑，并增加数据一致性校验。',
    'open',
    'P1',
    now,
    now,
    'quant-agent',
    '待验证：检查 update_account_total_value 相关逻辑',
    '数据不一致可能导致策略误判',
    None,
    '复盘发现，2026-06-15日报'
)

# 需求单2: sim_trades 为空但持仓存在，数据溯源缺失
task2 = (
    'REQ-071',
    'bug',
    'sim_trades 表为空但存在持仓记录，交易溯源断裂',
    '当前 sim_positions 有1条持仓（000001，100股），但 sim_trades、sim_orders、sim_fills 均为空。\n\n初始资金100000元，当前总资产约10106元，约89894元去向不明，无交易记录可查。\n\n可能原因：\n1. 持仓是手动INSERT的测试数据，未经过交易流程\n2. 交易记录写入逻辑有bug，交易成功但未记录到 sim_trades\n3. 数据库被清理过但持仓未同步清理\n\n建议：\n1. 清理 TestLoss 脏数据，规范测试数据管理\n2. 检查交易写入逻辑，确保每笔成交必写 sim_trades/sim_fills\n3. 增加数据完整性检查：持仓必须有对应开仓交易记录',
    'open',
    'P1',
    now,
    now,
    'quant-agent',
    '需要确认：该持仓是否手动插入的测试数据',
    '无法追溯资金去向，影响实盘对接',
    None,
    '复盘发现，2026-06-15日报'
)

# 需求单3: stock_name 脏数据（TestLoss 应为平安银行）
task3 = (
    'REQ-072',
    'bug',
    'sim_positions.stock_name 存测试脏数据（TestLoss 应为 平安银行）',
    'sim_positions 表中 stock_code=000001 的 stock_name 为 "TestLoss"，但 000001 实际是平安银行。\n\n影响：\n1. 日报显示错误股票名称\n2. 如果依赖 stock_name 进行展示或告警，会误导用户\n3. 数据质量差，影响后续数据分析\n\n建议：\n1. 在写入持仓时，强制用行情接口校验/填充 stock_name\n2. 增加数据校验：stock_name 不能是明显测试字符串（TestXXX、test、debug等）\n3. 清理现有脏数据',
    'open',
    'P2',
    now,
    now,
    'quant-agent',
    '清理 TestLoss 数据，从行情接口获取正确 stock_name',
    '脏数据影响数据质量和展示',
    None,
    '复盘发现，2026-06-15日报'
)

# 需求单4: 模拟盘无止损触发记录
task4 = (
    'REQ-073',
    'story',
    '增加每日止损/止盈自动检查与执行功能',
    '当前模拟盘复盘是手动触发的，缺少自动化的止损/止盈检查与执行机制。\n\n需求：\n1. 每个交易日收盘后，自动检查所有持仓的止损/止盈条件\n2. 触发止损时：自动下单卖出，记录止损执行结果\n3. 触发止盈时：发送通知提醒，可选自动卖出\n4. 检查 trailing_stop（移动止损）是否触发\n5. 将检查结果写入 sim_account_events 和日报\n\n参考：当前 sim_positions 有 trailing_stop_price 字段但从未被更新/使用。',
    'open',
    'P2',
    now,
    now,
    'quant-agent',
    '需要设计止损执行流程和通知机制',
    '当前无自动风控，实盘会有重大风险',
    None,
    '复盘发现，2026-06-15日报'
)

tasks = [task1, task2, task3, task4]
task_ids = []

for t in tasks:
    try:
        cursor.execute(
            "INSERT INTO tasks (id, type, title, description, status, priority, created_at, updated_at, assigned_to, result_notes, root_cause, fix_commit, work_notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            t
        )
        task_ids.append(t[0])
        print(f"✅ 已添加: {t[0]} - {t[2]}")
    except Exception as e:
        print(f"❌ 添加失败 {t[0]}: {e}")

conn.commit()
conn.close()

print(f"\n共添加 {len(task_ids)} 条需求单: {task_ids}")
