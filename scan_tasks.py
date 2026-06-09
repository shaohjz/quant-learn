#!/usr/bin/env python3
"""
扫描 pm/requirements 和 pm/bugs 目录，查找待处理的需求和Bug
"""
import os
import re
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path("C:/Users/Administrator/.openclaw/workspace/quant-learn")
REQUIREMENTS_DIR = PROJECT_ROOT / "pm" / "requirements"
BUGS_DIR = PROJECT_ROOT / "pm" / "bugs"

# 状态匹配正则
STATUS_PATTERN = re.compile(r'^\s*status:\s*(\S+)', re.IGNORECASE | re.MULTILINE)

def scan_files(directory, active_statuses):
    """扫描目录中的文件，返回匹配状态的文件列表"""
    results = []
    if not directory.exists():
        return results
    
    for file_path in directory.glob("*.md"):
        try:
            content = file_path.read_text(encoding="utf-8")
            match = STATUS_PATTERN.search(content)
            if match:
                status = match.group(1).lower()
                if status in active_statuses:
                    results.append({
                        "file": file_path.name,
                        "path": str(file_path),
                        "status": status
                    })
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
    
    return results

def main():
    # 扫描需求 (pending, in_progress)
    requirements = scan_files(REQUIREMENTS_DIR, {"pending", "in_progress"})
    
    # 扫描Bug (open, reopened, in_progress)
    bugs = scan_files(BUGS_DIR, {"open", "reopened", "in_progress"})
    
    print("=== 待处理需求 ===")
    for req in requirements:
        print(f"{req['file']}: {req['status']}")
    
    print("\n=== 待处理Bug ===")
    for bug in bugs:
        print(f"{bug['file']}: {bug['status']}")
    
    # 返回汇总信息
    total = len(requirements) + len(bugs)
    print(f"\n总计: {total} 个待处理项 ({len(requirements)} 个需求, {len(bugs)} 个Bug)")
    
    return total

if __name__ == "__main__":
    main()
