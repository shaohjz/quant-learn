"""REQ-038 单元测试：持仓数量硬上限风控

验证：
1. 总持仓数 >= max_total_positions 时，新 buy_zone 信号被拒绝
2. 单日新建仓位 >= max_daily_new_positions 时，第 3 个新仓被拒
3. 老仓位加仓不受 daily_new_position_limit 约束
4. 拒绝/通过时正确写入 review_decisions
"""
import sqlite3
import os
import sys
import tempfile
import datetime

# ── 准备临时测试数据库 ─────────────────────────────────────────
tmp_db = tempfile.mktemp(suffix='.db')
print(f'测试数据库: {tmp_db}')

conn = sqlite3.connect(tmp_db)
conn.execute('CREATE TABLE sim_account (id INTEGER PRIMARY KEY, cash REAL, total_value REAL)')
conn.execute(
    'CREATE TABLE sim_positions '
    '(id INTEGER PRIMARY KEY, account_id INTEGER, stock_code TEXT, quantity INTEGER)'
)
conn.execute(
    'CREATE TABLE sim_trades '
    '(id INTEGER PRIMARY KEY, account_id INTEGER, trade_date DATE, '
    ' stock_code TEXT, direction TEXT, signal_reason TEXT)'
)
conn.execute(
    'CREATE TABLE IF NOT EXISTS review_decisions '
    '(id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, stock_code TEXT, '
    ' trade_date DATE, decision_type TEXT, allowed INTEGER, reason TEXT)'
)
conn.execute('INSERT INTO sim_account VALUES (1, 200000, 200000)')
conn.commit()
conn.close()

# ── 导入被测模块 ───────────────────────────────────────────────
import importlib, types, sys, os, datetime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# 动态加载 sim_executor（在 scripts/ 下，需要把 scripts/ 加入 path）
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import sim_executor as executor
importlib.reload(executor)
executor._DB_PATH = tmp_db
executor._ACCOUNT_ID = 1
executor.MAX_TOTAL_POSITIONS = 3
executor.MAX_DAILY_NEW_POSITIONS = 2


def make_rule(code, level='buy_zone', name='测试股'):
    return {
        'code': code,
        'name': name,
        'level': level,
        'trigger': 10,
        'dir': 'below',
    }


def check(cond, msg):
    if cond:
        print(f'  [PASS] {msg}')
        return True
    else:
        print(f'  [FAIL] {msg}')
        return False


pass_n = 0
fail_n = 0


def mk_test(name, cond, msg):
    global pass_n, fail_n
    if check(cond, msg):
        pass_n += 1
    else:
        fail_n += 1


print('\n=== 测试 1: 总持仓数硬上限 ===')
conn = sqlite3.connect(tmp_db)
conn.execute("DELETE FROM sim_positions")
conn.execute("DELETE FROM review_decisions")
# 预置 3 个持仓（已达上限 3）
conn.execute("INSERT INTO sim_positions (account_id, stock_code, quantity) VALUES (1, '000001', 100)")
conn.execute("INSERT INTO sim_positions (account_id, stock_code, quantity) VALUES (1, '000002', 200)")
conn.execute("INSERT INTO sim_positions (account_id, stock_code, quantity) VALUES (1, '000003', 300)")
conn.commit()
conn.close()

rule1 = make_rule('000004')
action1 = executor.decide_action(rule1, 10.0)
mk_test('T1', action1 == 'NO_ACTION', '持仓满 3 只时新股票被拒绝 (NO_ACTION)')

conn = sqlite3.connect(tmp_db)
rd1 = conn.execute(
    "SELECT decision_type, allowed FROM review_decisions WHERE stock_code='000004' ORDER BY id DESC LIMIT 1"
).fetchone()
conn.close()
mk_test('T1b', rd1 is not None and rd1[0] == 'position_count_limit' and rd1[1] == 0,
       '拒绝时写入 review_decisions (position_count_limit, allowed=0)')


print('\n=== 测试 2: 单日新建仓位数硬上限 ===')
conn = sqlite3.connect(tmp_db)
conn.execute("DELETE FROM sim_positions")
conn.execute("DELETE FROM sim_trades")
conn.execute("DELETE FROM review_decisions")
conn.execute("INSERT INTO sim_positions (account_id, stock_code, quantity) VALUES (1, '000001', 100)")
today = datetime.date.today().strftime('%Y-%m-%d')
conn.execute(
    "INSERT INTO sim_trades (account_id, trade_date, stock_code, direction, signal_reason) "
    "VALUES (1, ?, '000002', 'BUY', 'buy_zone signal')", (today,)
)
conn.execute(
    "INSERT INTO sim_trades (account_id, trade_date, stock_code, direction, signal_reason) "
    "VALUES (1, ?, '000003', 'BUY', 'buy_zone signal')", (today,)
)
conn.commit()
conn.close()

rule2 = make_rule('000005')
action2 = executor.decide_action(rule2, 10.0)
mk_test('T2', action2 == 'NO_ACTION', '今日已新建 2 仓，第 3 个新仓被拒 (NO_ACTION)')

conn = sqlite3.connect(tmp_db)
rd2 = conn.execute(
    "SELECT decision_type, allowed FROM review_decisions WHERE stock_code='000005' ORDER BY id DESC LIMIT 1"
).fetchone()
conn.close()
mk_test('T2b', rd2 is not None and rd2[0] == 'daily_new_position_limit' and rd2[1] == 0,
       '拒绝时写入 review_decisions (daily_new_position_limit, allowed=0)')


print('\n=== 测试 3: 老仓位加仓不受 daily_new_position_limit 约束 ===')
# 000001 已有持仓，加仓不属于"新建"，不应因 daily_new_position_limit 被拒
rule3 = make_rule('000001')
action3 = executor.decide_action(rule3, 10.0)
conn = sqlite3.connect(tmp_db)
rd3 = conn.execute(
    "SELECT decision_type FROM review_decisions "
    "WHERE stock_code='000001' AND decision_type='daily_new_position_limit'"
).fetchone()
conn.close()
mk_test('T3', rd3 is None, '已有仓位加仓不因 daily_new_position_limit 被拒')


print('\n=== 测试 4: 清理临时文件 ===')
try:
    os.unlink(tmp_db)
    print(f'  [PASS] 临时数据库 {tmp_db} 已删除')
except Exception as e:
    print(f'  [WARN] 删除临时数据库失败: {e}')

print(f'\n=== 结果: {pass_n} pass, {fail_n} fail ===')
sys.exit(0 if fail_n == 0 else 1)
