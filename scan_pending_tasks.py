#!/usr/bin/env python3
"""
扫描 pm/requirements/ 和 pm/bugs/ 中的待处理任务
"""
import os
import re
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path("C:/Users/Administrator/.openclaw/workspace/quant-learn")
REQ_DIR = PROJECT_ROOT / "pm" / "requirements"
BUG_DIR = PROJECT_ROOT / "pm" / "bugs"

def scan_files(directory, task_type):
    """扫描目录中的文件，返回待处理的任务"""
    pending_tasks = []
    
    if not directory.exists():
        print(f"目录不存在: {directory}")
        return pending_tasks
    
    for file_path in directory.glob("*.md"):
        try:
            content = file_path.read_text(encoding="utf-8")
            
            # 查找状态字段
            status_match = re.search(r'状态:\s*(\S+)', content)
            if not status_match:
                continue
                
            status = status_match.group(1).strip()
            
            # 检查是否为待处理状态
            if task_type == "requirement":
                if status in ["pending", "in_progress"]:
                    # 提取优先级
                    priority_match = re.search(r'优先级:\s*(\S+)', content)
                    priority = priority_match.group(1).strip() if priority_match else "P3"
                    
                    pending_tasks.append({
                        "file": file_path.name,
                        "id": file_path.stem,
                        "type": "requirement",
                        "status": status,
                        "priority": priority,
                        "path": str(file_path)
                    })
            elif task_type == "bug":
                if status in ["open", "reopened", "in_progress"]:
                    # 提取优先级
                    priority_match = re.search(r'优先级:\s*(\S+)', content)
                    priority = priority_match.group(1).strip() if priority_match else "P3"
                    
                    pending_tasks.append({
                        "file": file_path.name,
                        "id": file_path.stem,
                        "type": "bug",
                        "status": status,
                        "priority": priority,
                        "path": str(file_path)
                    })
                    
        except Exception as e:
            print(f"读取文件失败 {file_path}: {e}")
    
    return pending_tasks

def priority_score(task):
    """计算优先级分数（用于排序）"""
    priority = task["priority"]
    status = task["status"]
    task_type = task["type"]
    
    # 基础分数
    score = 0
    
    # 优先级分数
    if priority.startswith("S") or priority.startswith("P0"):
        score += 1000
    elif priority.startswith("P1"):
        score += 100
    elif priority.startswith("P2"):
        score += 10
    else:
        score += 1
    
    # 状态分数（reopened > open > in_progress > pending）
    if status == "reopened":
        score += 500
    elif status == "open":
        score += 400
    elif status == "in_progress":
        score += 300
    
    # Bug 优先于需求
    if task_type == "bug":
        score += 50
    
    return score

def main():
    print("=" * 60)
    print("扫描待处理任务")
    print("=" * 60)
    
    # 扫描需求
    print("\n1. 扫描需求...")
    requirements = scan_files(REQ_DIR, "requirement")
    print(f"   找到 {len(requirements)} 个待处理需求")
    
    # 扫描Bug
    print("\n2. 扫描Bug...")
    bugs = scan_files(BUG_DIR, "bug")
    print(f"   找到 {len(bugs)} 个待处理Bug")
    
    # 合并所有任务
    all_tasks = requirements + bugs
    
    if not all_tasks:
        print("\n✅ 没有待处理的任务")
        return
    
    # 按优先级排序
    all_tasks.sort(key=priority_score, reverse=True)
    
    print("\n" + "=" * 60)
    print("待处理任务列表（按优先级排序）")
    print("=" * 60)
    
    for i, task in enumerate(all_tasks, 1):
        print(f"\n{i}. [{task['type']}] {task['id']}")
        print(f"   文件: {task['file']}")
        print(f"   状态: {task['status']}")
        print(f"   优先级: {task['priority']}")
        print(f"   路径: {task['path']}")
    
    print("\n" + "=" * 60)
    print(f"总计: {len(all_tasks)} 个待处理任务")
    print("=" * 60)
    
    # 输出最高优先级的任务
    if all_tasks:
        top_task = all_tasks[0]
        print("\n🎯 最高优先级任务:")
        print(f"   {top_task['type'].upper()}: {top_task['id']}")
        print(f"   优先级: {top_task['priority']}")
        print(f"   状态: {top_task['status']}")

if __name__ == "__main__":
    main()