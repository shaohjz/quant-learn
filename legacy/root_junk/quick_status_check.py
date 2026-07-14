#!/usr/bin/env python3
"""
快速检查所有任务的当前状态
"""
import os
import re
from pathlib import Path

base_dir = r'C:\Users\Administrator\.openclaw\workspace\quant-learn'

# 检查需求文件
print("=== 需求文件状态检查 ===")
req_dir = os.path.join(base_dir, 'pm', 'requirements')
for file_path in Path(req_dir).glob('*.md'):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 查找状态字段
        status_match = re.search(r'\|\s*\*\*状态\*\*\s*\|\s*(\S+)\s*\|', content)
        if not status_match:
            status_match = re.search(r'-\s*\*\*状态\*\*:?\s*(\S+)', content)
        
        if status_match:
            status = status_match.group(1).strip()
            if status.lower() in ['pending', 'in_progress']:
                print(f"待处理需求: {file_path.name} - 状态: {status}")
    except Exception as e:
        pass

# 检查Bug文件
print("\n=== Bug文件状态检查 ===")
bug_dir = os.path.join(base_dir, 'pm', 'bugs')
for file_path in Path(bug_dir).glob('*.md'):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 查找状态字段
        status_match = re.search(r'\|\s*\*\*状态\*\*\s*\|\s*(\S+)\s*\|', content)
        if not status_match:
            status_match = re.search(r'-\s*\*\*状态\*\*:?\s*(\S+)', content)
        
        if status_match:
            status = status_match.group(1).strip()
            if status.lower() in ['open', 'reopened', 'in_progress']:
                print(f"待处理Bug: {file_path.name} - 状态: {status}")
    except Exception as e:
        pass

print("\n检查完成")
