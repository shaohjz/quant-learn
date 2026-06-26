#!/usr/bin/env python3
"""
QMT 启动脚本
用于确保 QMT 交易端在系统启动时自动运行
"""
import os
import sys
import subprocess
import time

QMT_EXE_PATH = r"D:\国金QMT交易端模拟\bin.x64\XtMiniQmt.exe"
QMT_WORKING_DIR = r"D:\国金QMT交易端模拟\bin.x64"

def is_qmt_running():
    """检查 QMT 是否正在运行"""
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq XtMiniQmt.exe", "/NH"],
        capture_output=True,
        text=True
    )
    return "XtMiniQmt.exe" in result.stdout

def start_qmt():
    """启动 QMT 交易端"""
    if is_qmt_running():
        print("[信息] QMT 已经在运行")
        return True
    
    print(f"[信息] 正在启动 QMT: {QMT_EXE_PATH}")
    
    try:
        subprocess.Popen(
            QMT_EXE_PATH,
            cwd=QMT_WORKING_DIR,
            shell=False
        )
        
        # 等待 QMT 启动
        for i in range(10):
            time.sleep(2)
            if is_qmt_running():
                print(f"[成功] QMT 已启动（等待 {i*2} 秒）")
                return True
        
        print("[警告] QMT 进程已启动但未检测到，请手动检查")
        return False
        
    except Exception as e:
        print(f"[错误] 启动 QMT 失败: {e}")
        return False

def main():
    print("=" * 60)
    print("QMT 启动脚本")
    print("=" * 60)
    
    if start_qmt():
        print("\n[成功] QMT 启动成功")
        sys.exit(0)
    else:
        print("\n[错误] QMT 启动失败")
        sys.exit(1)

if __name__ == "__main__":
    main()
