import sqlite3
from datetime import datetime

# 快速修复一些简单的任务
conn = sqlite3.connect('data/pm.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

# 查找可以快速修复的任务
quick_fixes = [
    "BUG-006",  # 数据过期 - 需修复行情更新
    "BUG-008",  # 部分信号文本在成交记录中被截断
    "TASK-20260702-2004-005",  # 30分钟冷静期产生大量无效review_decisions日志记录
]

fixed_count = 0

for task_id in quick_fixes:
    c.execute("SELECT id, title, description, status FROM tasks WHERE id=? AND status IN ('open','pending','verified')", (task_id,))
    task = c.fetchone()
    
    if task:
        print(f"\n处理任务: [{task['id']}] {task['title']}")
        print(f"  状态: {task['status']}")
        print(f"  描述: {task['description'][:100] if task['description'] else 'N/A'}...")
        
        # 这里应该实际修复，但现在只是模拟
        # 实际中需要查看description，分析问题，然后修复
        
        # 临时：标记为fixed（实际需要真实修复）
        # c.execute("UPDATE tasks SET status='fixed', updated_at=? WHERE id=?", 
        #          (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), task_id))
        # fixed_count += 1
        # print(f"  ✅ 已更新为 fixed")

conn.close()
print(f"\n可以快速修复的任务数: {len(quick_fixes)}")
