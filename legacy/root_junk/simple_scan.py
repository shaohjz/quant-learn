#!/usr/bin/env python3
"""
简单扫描待处理的任务
"""
import os
import re

PROJECT_ROOT = "C:/Users/Administrator/.openclaw/workspace/quant-learn"
REQUIREMENTS_DIR = os.path.join(PROJECT_ROOT, "pm", "requirements")
BUGS_DIR = os.path.join(PROJECT_ROOT, "pm", "bugs")

def check_file(file_path, file_type):
    """检查文件状态"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 提取状态 - 使用简单的字符串查找
        status = "unknown"
        
        # 查找 "状态:" 或 "**状态**:"
        status_patterns = [
            r'\*\*状态\*\*:\s*(.+?)[\n\r]',
            r'状态:\s*(.+?)[\n\r]',
            r'- \*\*状态\*\*:\s*(.+?)[\n\r]'
        ]
        
        for pattern in status_patterns:
            match = re.search(pattern, content)
            if match:
                status = match.group(1).strip()
                break
        
        # 提取优先级
        priority = "P3"
        priority_patterns = [
            r'\*\*优先级\*\*:\s*(.+?)[\n\r]',
            r'优先级:\s*(.+?)[\n\r]',
            r'\*\*严重程度\*\*:\s*(.+?)[\n\r]'
        ]
        
        for pattern in priority_patterns:
            match = re.search(pattern, content)
            if match:
                priority_text = match.group(1).strip()
                # 简化优先级
                if 'S0' in priority_text or '高' in priority_text:
                    priority = "S0"
                elif 'S1' in priority_text or '中' in priority_text:
                    priority = "S1"
                elif 'P0' in priority_text:
                    priority = "P0"
                elif 'P1' in priority_text:
                    priority = "P1"
                else:
                    priority = priority_text
                break
        
        return status, priority
        
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return "unknown", "P3"

def main():
    """主函数"""
    tasks = []
    
    # 扫描需求文件
    if os.path.exists(REQUIREMENTS_DIR):
        print("=== 扫描需求文件 ===")
        for filename in os.listdir(REQUIREMENTS_DIR):
            if filename.endswith('.md'):
                file_path = os.path.join(REQUIREMENTS_DIR, filename)
                status, priority = check_file(file_path, 'requirement')
                
                print(f"{filename}: 状态={status}, 优先级={priority}")
                
                # 检查是否是待处理状态
                if status in ['pending', 'in_progress']:
                    tasks.append({
                        'type': 'requirement',
                        'id': filename.replace('.md', ''),
                        'status': status,
                        'priority': priority,
                        'path': file_path
                    })
    
    # 扫描Bug文件
    if os.path.exists(BUGS_DIR):
        print("\n=== 扫描Bug文件 ===")
        for filename in os.listdir(BUGS_DIR):
            if filename.endswith('.md'):
                file_path = os.path.join(BUGS_DIR, filename)
                status, priority = check_file(file_path, 'bug')
                
                print(f"{filename}: 状态={status}, 优先级={priority}")
                
                # 检查是否是待处理状态
                if status in ['open', 'reopened', 'in_progress']:
                    tasks.append({
                        'type': 'bug',
                        'id': filename.replace('.md', ''),
                        'status': status,
                        'priority': priority,
                        'path': file_path
                    })
    
    # 输出结果
    print(f"\n=== 扫描结果 ===")
    print(f"找到 {len(tasks)} 个待处理任务")
    
    if not tasks:
        print("NO_TASK")
        return
    
    # 简单排序：按优先级和类型
    def sort_key(task):
        # 简单排序逻辑
        type_order = {'bug': 0, 'requirement': 1}
        priority_order = {'S0': 0, 'S1': 1, 'P0': 2, 'S2': 3, 'P1': 4, 'S3': 5, 'P2': 6}
        
        type_val = type_order.get(task['type'], 9)
        priority_val = priority_order.get(task['priority'], 9)
        
        return (type_val, priority_val, task['id'])
    
    sorted_tasks = sorted(tasks, key=sort_key)
    
    print("\n=== 待处理任务列表 ===")
    for i, task in enumerate(sorted_tasks, 1):
        print(f"{i}. {task['type'].upper()}: {task['id']}")
        print(f"   状态: {task['status']}, 优先级: {task['priority']}")
        print(f"   路径: {task['path']}")
    
    # 选择最高优先级任务
    if sorted_tasks:
        top_task = sorted_tasks[0]
        print(f"\n=== 选择最高优先级任务 ===")
        print(f"类型: {top_task['type']}")
        print(f"ID: {top_task['id']}")
        print(f"状态: {top_task['status']}")
        print(f"优先级: {top_task['priority']}")
        print(f"路径: {top_task['path']}")
        
        # 这里应该开始处理这个任务
        # 但根据题目要求，如果没有待处理项，回复NO_TASK
        # 如果有，应该开始开发流程
        print("\n开始处理任务...")
        # 注意：实际开发中这里应该调用相应的处理函数
        # 但根据题目要求，如果没有待处理项才回复NO_TASK
        # 所以这里应该继续处理任务，而不是回复NO_TASK

if __name__ == "__main__":
    main()