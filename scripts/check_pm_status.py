#!/usr/bin/env python3
"""
产品经理每日迭代汇报脚本
检查 pm.db 中的任务状态并生成日报
"""

import sqlite3
import json
from datetime import datetime, timedelta

def check_pm_database(db_path):
    """检查 PM 数据库中的任务状态"""
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 获取所有表格
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print('📊 数据库表格:', [t[0] for t in tables])
    
    # 检查 tasks 表是否存在
    if not any('tasks' in t[0].lower() for t in tables):
        print('⚠️  未找到 tasks 表，请检查数据库结构')
        return
    
    # 检查 tasks 表结构
    cursor.execute('PRAGMA table_info(tasks)')
    columns = cursor.fetchall()
    column_names = [c[1] for c in columns]
    print(f'📋 Tasks 表字段: {column_names}')
    
    # 统计各状态任务数量
    cursor.execute('''
        SELECT status, COUNT(*) as count 
        FROM tasks 
        GROUP BY status
        ORDER BY count DESC
    ''')
    status_counts = cursor.fetchall()
    
    print('\n=== 📈 任务状态统计 ===')
    total_tasks = 0
    status_summary = {}
    for status, count in status_counts:
        print(f'  {status}: {count}')
        total_tasks += count
        status_summary[status] = count
    print(f'  📊 总计: {total_tasks} 个任务')
    
    # 获取所有任务详情，按状态和优先级排序
    cursor.execute('''
        SELECT id, title, status, priority, assignee, created_at, updated_at, description
        FROM tasks
        ORDER BY 
            CASE status 
                WHEN "blocked" THEN 1
                WHEN "in_progress" THEN 2
                WHEN "todo" THEN 3
                WHEN "done" THEN 4
                ELSE 5
            END,
            CASE priority
                WHEN "high" THEN 1
                WHEN "medium" THEN 2
                WHEN "low" THEN 3
                ELSE 4
            END,
            updated_at DESC
    ''')
    
    tasks = cursor.fetchall()
    
    print('\n=== 📝 任务详情（按状态和优先级排序）===')
    
    # 按状态分组显示
    current_status = None
    blocked_tasks = []
    in_progress_tasks = []
    todo_tasks = []
    done_tasks = []
    
    for task in tasks:
        task_id, title, status, priority, assignee, created_at, updated_at, desc = task
        
        task_info = {
            'id': task_id,
            'title': title,
            'status': status,
            'priority': priority,
            'assignee': assignee,
            'created_at': created_at,
            'updated_at': updated_at,
            'description': desc
        }
        
        if status == 'blocked':
            blocked_tasks.append(task_info)
        elif status == 'in_progress':
            in_progress_tasks.append(task_info)
        elif status == 'todo':
            todo_tasks.append(task_info)
        elif status == 'done':
            done_tasks.append(task_info)
    
    # 显示阻塞任务（最优先）
    if blocked_tasks:
        print('\n🔴 阻塞任务 (BLOCKED):')
        for task in blocked_tasks:
            print(f'  ❌ #{task["id"]} - {task["title"]}')
            print(f'      优先级: {task["priority"]}, 负责人: {task["assignee"]}')
            print(f'      创建: {task["created_at"]}, 更新: {task["updated_at"]}')
            if task["description"]:
                desc = task["description"][:100] + "..." if len(task["description"]) > 100 else task["description"]
                print(f'      描述: {desc}')
            print()
    
    # 显示进行中任务
    if in_progress_tasks:
        print('\n🟡 进行中任务 (IN PROGRESS):')
        for task in in_progress_tasks:
            print(f'  🔄 #{task["id"]} - {task["title"]}')
            print(f'      优先级: {task["priority"]}, 负责人: {task["assignee"]}')
            print(f'      创建: {task["created_at"]}, 更新: {task["updated_at"]}')
            if task["description"]:
                desc = task["description"][:100] + "..." if len(task["description"]) > 100 else task["description"]
                print(f'      描述: {desc}')
            print()
    
    # 显示待办任务
    if todo_tasks:
        print('\n🟢 待办任务 (TODO):')
        for task in todo_tasks:
            print(f'  📋 #{task["id"]} - {task["title"]}')
            print(f'      优先级: {task["priority"]}, 负责人: {task["assignee"]}')
            print(f'      创建: {task["created_at"]}, 更新: {task["updated_at"]}')
            if task["description"]:
                desc = task["description"][:100] + "..." if len(task["description"]) > 100 else task["description"]
                print(f'      描述: {desc}')
            print()
    
    # 显示已完成任务（简要）
    if done_tasks:
        print(f'\n✅ 已完成任务 (DONE): {len(done_tasks)} 个')
        for task in done_tasks[-5:]:  # 只显示最近5个
            print(f'  ✓ #{task["id"]} - {task["title"]}')
        if len(done_tasks) > 5:
            print(f'  ... 还有 {len(done_tasks) - 5} 个已完成任务')
        print()
    
    # 生成迭代汇报
    print('\n=== 📊 迭代汇报总结 ===')
    
    # 本周目标完成情况（假设本周从周一开始）
    today = datetime.now()
    start_of_week = today - timedelta(days=today.weekday())
    
    cursor.execute('''
        SELECT COUNT(*) 
        FROM tasks 
        WHERE status = "done" 
        AND date(updated_at) >= date(?)
    ''', (start_of_week.strftime('%Y-%m-%d'),))
    
    completed_this_week = cursor.fetchone()[0]
    
    print(f'📅 本周已完成任务: {completed_this_week} 个')
    print(f'📈 总体进度: {len(done_tasks)}/{total_tasks} ({len(done_tasks)/total_tasks*100:.1f}%)')
    
    # 阻塞项说明
    if blocked_tasks:
        print('\n🚫 当前阻塞项:')
        for task in blocked_tasks:
            print(f'  - #{task["id"]} {task["title"]} (负责人: {task["assignee"]})')
    else:
        print('\n✅ 无阻塞项')
    
    # 下一步计划
    print('\n🎯 下一步计划:')
    if in_progress_tasks:
        print('  1. 继续推进进行中的任务:')
        for task in in_progress_tasks[:3]:  # 显示前3个
            print(f'     - #{task["id"]} {task["title"]}')
    
    if todo_tasks:
        # 按优先级排序待办任务
        high_priority_todos = [t for t in todo_tasks if t["priority"] == "high"]
        if high_priority_todos:
            print('  2. 开始高优先级待办任务:')
            for task in high_priority_todos[:3]:
                print(f'     - #{task["id"]} {task["title"]}')
    
    if blocked_tasks:
        print('  3. 解决阻塞项:')
        for task in blocked_tasks:
            print(f'     - #{task["id"]} {task["title"]}')
    
    conn.close()
    
    # 返回结构化数据用于生成日报
    return {
        'total_tasks': total_tasks,
        'status_summary': status_summary,
        'blocked_tasks': blocked_tasks,
        'in_progress_tasks': in_progress_tasks,
        'todo_tasks': todo_tasks,
        'done_tasks': done_tasks,
        'completed_this_week': completed_this_week
    }

if __name__ == '__main__':
    db_path = 'data/pm.db'
    print('🔍 开始检查产品经理数据库...')
    print('=' * 50)
    
    try:
        result = check_pm_database(db_path)
        print('\n' + '=' * 50)
        print('✅ 检查完成！')
        
        # 将结果保存到 JSON 文件，供后续生成日报使用
        with open('data/pm_status_report.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print('📄 详细报告已保存到 data/pm_status_report.json')
        
    except Exception as e:
        print(f'❌ 检查过程中出现错误: {e}')
        import traceback
        traceback.print_exc()