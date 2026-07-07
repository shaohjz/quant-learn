#!/usr/bin/env python3
"""清理重复任务并显示open任务"""
import sqlite3

def cleanup():
    # 连接PM数据库
    conn = sqlite3.connect('data/pm.db')
    cursor = conn.cursor()
    
    # 删除重复的REQ-070（假设REQ-069是正确的）
    cursor.execute("DELETE FROM tasks WHERE id = ?", ('REQ-070',))
    deleted = cursor.rowcount
    print(f'已删除 REQ-070 (删除了 {deleted} 条记录)')
    
    # 显示当前open状态的任务
    cursor.execute("""
        SELECT id, title, priority 
        FROM tasks 
        WHERE status = 'open' 
        ORDER BY 
            CASE priority 
                WHEN 'P0' THEN 1
                WHEN 'P1' THEN 2
                WHEN 'P2' THEN 3
                ELSE 4
            END,
            id 
        LIMIT 10
    """)
    open_tasks = cursor.fetchall()
    
    print(f'\n当前open状态的任务 (前10个):')
    for task in open_tasks:
        print(f'  {task[0]}: {task[1]} [{task[2]}]')
    
    conn.close()

if __name__ == '__main__':
    cleanup()
