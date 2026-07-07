#!/usr/bin/env python3
"""添加数据不一致bug到PM系统"""
import sqlite3
from datetime import datetime

def add_task():
    # 连接PM数据库
    conn = sqlite3.connect('data/pm.db')
    cursor = conn.cursor()
    
    # 检查当前最大ID
    cursor.execute('SELECT id FROM tasks ORDER BY id DESC LIMIT 1')
    last_id = cursor.fetchone()
    if last_id:
        num = int(last_id[0].split('-')[1])
        new_id = f'REQ-{num + 1:03d}'
    else:
        new_id = 'REQ-001'
    
    print(f'新任务ID: {new_id}')
    
    # 任务描述
    description = """## 问题描述
复盘发现两个账户的现金与总值数据倒挂：

### 账户1 (learn)
- 当前总值: ¥13,872.39
- 可用资金: ¥22,527.39
- **问题**: 现金 > 总值，逻辑错误

### 账户2 (real_portfolio)
- 当前总值: ¥9,635.41
- 可用资金: ¥24,641.41
- **问题**: 无持仓但总值与现金不一致

## 影响
1. 所有基于total_value的计算（收益率、风险指标）都错误
2. 自动交易策略可能基于错误数据执行
3. 报告和分析结果不可信

## 可能原因
1. sim_account表的total_value字段计算逻辑错误
2. 持仓市值没有正确汇总到total_value
3. 数据库触发器或更新逻辑有bug

## 建议措施
1. 立即暂停自动交易
2. 核查sim_account更新逻辑
3. 重新计算所有账户的total_value
4. 添加数据一致性检查
"""
    
    # 添加数据不一致问题任务
    task_data = (
        new_id,
        'bug',
        '紧急：模拟盘账户数据不一致',
        description,
        'open',
        'P0',
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    
    cursor.execute("""
        INSERT INTO tasks (id, type, title, description, status, priority, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, task_data)
    
    conn.commit()
    conn.close()
    
    print(f"✅ 已添加任务: {new_id}")
    print(f"标题: 紧急：模拟盘账户数据不一致")
    print(f"优先级: P0")
    print(f"状态: open")
    print(f"\n任务描述已保存到数据库，请通过PM系统查看完整描述")

if __name__ == '__main__':
    add_task()
