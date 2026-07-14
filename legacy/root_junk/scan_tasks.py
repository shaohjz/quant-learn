#!/usr/bin/env python3
"""
扫描 pm/requirements/ 和 pm/bugs/ 中的任务状态
"""
import os
import re
from pathlib import Path

def extract_status(file_path):
    """从文件中提取状态"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 查找状态行
        status_match = re.search(r'\|\s*\*\*状态\*\*\s*\|\s*(\S+)', content)
        if not status_match:
            status_match = re.search(r'-\s*\*\*状态\*\*:?\s*(\S+)', content)
        
        if status_match:
            status = status_match.group(1).strip()
            return status
        return None
    except Exception as e:
        print(f"读取文件失败 {file_path}: {e}")
        return None

def extract_priority(file_path):
    """从文件中提取优先级"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 查找优先级行
        priority_match = re.search(r'\|\s*\*\*优先级\*\*\s*\|\s*(\S+)', content)
        if not priority_match:
            priority_match = re.search(r'-\s*\*\*优先级\*\*:?\s*(\S+)', content)
        
        if priority_match:
            priority = priority_match.group(1).strip()
            return priority
        return None
    except Exception as e:
        return None

def scan_directory(directory, task_type):
    """扫描目录，返回待处理的任务列表"""
    tasks = []
    pending_statuses = ['pending', 'in_progress'] if task_type == 'requirement' else ['open', 'reopened', 'in_progress']
    
    try:
        for file_path in Path(directory).glob('*.md'):
            status = extract_status(file_path)
            priority = extract_priority(file_path)
            
            if status in pending_statuses:
                tasks.append({
                    'file': file_path.name,
                    'path': str(file_path),
                    'status': status,
                    'priority': priority,
                    'type': task_type
                })
    except Exception as e:
        print(f"扫描目录失败 {directory}: {e}")
    
    return tasks

def main():
    base_dir = r'C:\Users\Administrator\.openclaw\workspace\quant-learn'
    
    # 扫描需求
    req_dir = os.path.join(base_dir, 'pm', 'requirements')
    requirements = scan_directory(req_dir, 'requirement')
    
    # 扫描Bug
    bug_dir = os.path.join(base_dir, 'pm', 'bugs')
    bugs = scan_directory(bug_dir, 'bug')
    
    # 合并所有任务
    all_tasks = requirements + bugs
    
    # 按优先级排序
    priority_order = {'S0': 0, 'S1': 1, 'P0': 2, 'P1': 3, 'P2': 4, 'P3': 5}
    
    def sort_key(task):
        priority = task.get('priority', 'P3')
        # 提取优先级字母和数字
        match = re.match(r'([A-Z]+)(\d*)', priority)
        if match:
            letter = match.group(1)
            number = int(match.group(2)) if match.group(2) else 0
            return (priority_order.get(letter, 99), number)
        return (99, 0)
    
    all_tasks.sort(key=sort_key)
    
    # 输出结果
    if all_tasks:
        print(f"找到 {len(all_tasks)} 个待处理任务：")
        print("=" * 80)
        for i, task in enumerate(all_tasks, 1):
            print(f"{i}. [{task['type'].upper()}] {task['file']}")
            print(f"   状态: {task['status']}, 优先级: {task['priority']}")
            print(f"   路径: {task['path']}")
            print("-" * 80)
        
        # 输出最高优先级的任务
        if all_tasks:
            top_task = all_tasks[0]
            print(f"\n最高优先级任务：")
            print(f"类型: {top_task['type']}")
            print(f"文件: {top_task['file']}")
            print(f"状态: {top_task['status']}")
            print(f"优先级: {top_task['priority']}")
    else:
        print("没有待处理的任务")

if __name__ == '__main__':
    main()
