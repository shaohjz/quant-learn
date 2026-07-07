#!/usr/bin/env python3
"""添加复盘发现的问题到PM数据库"""
import sqlite3
from datetime import datetime
import uuid

def add_task(task_type, title, description, priority='P2', status='pending'):
    """添加新任务到PM数据库"""
    conn = sqlite3.connect('data/pm.db')
    
    task_id = f"TASK-{datetime.now().strftime('%Y%m%d-%H%M')}-{str(uuid.uuid4())[:4]}"
    
    now = datetime.now().isoformat()
    
    conn.execute('''
        INSERT INTO tasks (id, type, title, description, status, priority, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (task_id, task_type, title, description, status, priority, now, now))
    
    conn.commit()
    conn.close()
    
    print(f"✅ 已添加任务: {task_id} - {title}")
    return task_id

if __name__ == '__main__':
    # 复盘发现的问题
    
    # 1. 测试数据污染真实持仓
    add_task(
        task_type='bug',
        title='测试股票(Test0/1/2)污染模拟盘真实持仓数据',
        description='''模拟盘持仓中出现测试股票(Test0/000000, Test1/000001, Test2/000002)，导致：
        - 市值计算不准确
        - 2026-07-03当日盈亏+59885.07元异常（可能由测试数据导致）
        - 影响复盘报告准确性
        
        建议：
        1. 清理sim_positions表中的测试股票
        2. 在sim_executor中增加测试股票过滤逻辑
        3. 增加数据验证逻辑，防止测试数据进入生产模拟盘''',
        priority='P1',
        status='pending'
    )
    
    # 2. 建投能源同日买卖异常
    add_task(
        task_type='bug',
        title='建投能源(000600)同日触发买卖导致无效交易',
        description='''2026-07-03 09:30:04买入建投能源1000股@9.14，同日触发SELL信号卖出。
        可能原因：
        1. buy_strong信号与trend_break信号时间太近
        2. 缺乏成交确认与持仓锁定机制
        3. 需要增加交易冷却期（如REQ-033已实现但似乎未生效）
        
        建议：
        1. 检查REQ-033（日内资金预算与冷静期）是否生效
        2. 增加买卖信号确认机制（如收盘确认）
        3. 同城买卖应记录为无效交易并从复盘报告中标记''',
        priority='P1',
        status='pending'
    )
    
    # 3. 立讯精密接近止损
    add_task(
        task_type='task',
        title='立讯精密(002475)接近跟踪止损价，需要监控',
        description='''当前价格64.95，跟踪止损价62.31，距离仅4.1%。
        需要在下一个交易日开盘后密切监控，如果跌破62.31应立即执行止损。
        
        建议：
        1. 在intraday-watch中增加临近止损预警
        2. 考虑提前部分止盈（如价格反弹至67以上）''',
        priority='P2',
        status='pending'
    )
    
    # 4. NAV数据缺失
    add_task(
        task_type='bug',
        title='非交易日没有NAV数据导致复盘报告生成失败',
        description='''2026-07-05（周日）执行复盘时，因无NAV数据导致报告生成不完整。
        
        建议：
        1. 在generate_daily_report中自动识别最近交易日
        2. 增加交易日历判断逻辑
        3. 周末/节假日执行复盘时应使用最近一个交易日的数据''',
        priority='P2',
        status='pending'
    )
    
    print("\n✅ 所有任务已添加到PM数据库")
