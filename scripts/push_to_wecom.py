#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送日报到企微群"""

import subprocess
import sys

def push_to_wecom(message):
    """推送消息到企微群"""
    try:
        # 使用wecom_webhook模块推送
        result = subprocess.run([
            'python', '-c', 
            f'from scripts.wecom_webhook import push_markdown; push_markdown("""{message}""")'
        ], 
        capture_output=True, 
        text=True,
        cwd='C:/Users/Administrator/.openclaw/workspace/quant-learn'
        )
        
        if result.returncode == 0:
            print("✅ 成功推送到企微群")
            return True
        else:
            print(f"❌ 推送失败: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ 推送异常: {e}")
        return False

if __name__ == '__main__':
    if len(sys.argv) > 1:
        message = sys.argv[1]
    else:
        message = "测试消息"
    
    push_to_wecom(message)
