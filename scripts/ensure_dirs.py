#!/usr/bin/env python3
from __future__ import annotations

"""确保项目所需目录都存在，如果不存在则创建"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DIRS = [
    ROOT / "docs" / "reports",
    ROOT / "docs" / "reviews", 
    ROOT / "docs" / "logs",
    ROOT / "logs",
    ROOT / "output" / "cleanup_logs",
    ROOT / "pm" / "test_reports",
    ROOT / "data" / "market",
    ROOT / "data" / "reports",
]

def ensure_dirs():
    """创建所有需要的目录"""
    for d in REQUIRED_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    return [str(d) for d in REQUIRED_DIRS]

if __name__ == "__main__":
    created = ensure_dirs()
    print(f"✅ 确保目录存在: {len(created)} 个目录")
    for d in created:
        print(f"  - {d}")
