#!/usr/bin/env python
"""
scripts/iwiki_helper.py - iwiki MCP 调用封装

通过 subprocess 调用 mcporter，避开 PowerShell 引号转义噩梦。
"""
import subprocess
import json
import sys
import shlex
import os
import shutil

# 查找 mcporter 可执行文件
MCPORTER = shutil.which('mcporter') or shutil.which('mcporter.cmd') or 'mcporter'
if not os.path.isfile(MCPORTER):
    # fallback 到常见路径
    candidates = [
        r'C:\openclaw\openclaw\runtime\node-v22.22.0-win-x64\mcporter.cmd',
        r'C:\openclaw\openclaw\runtime\node-v22.22.0-win-x64\mcporter',
    ]
    for c in candidates:
        if os.path.isfile(c):
            MCPORTER = c
            break


def call_iwiki(tool: str, **kwargs) -> dict:
    """
    调用 mcporter 的 iwiki 工具。
    
    Args:
        tool: 工具名，如 'getDocument'
        **kwargs: 工具参数
    
    Returns:
        dict: 返回 {'ok': bool, 'data': ..., 'error': ...}
    """
    args = [MCPORTER, 'call', f'iwiki.{tool}']
    if kwargs:
        args.extend(['--args', json.dumps(kwargs)])
    
    try:
        # 在 Windows 上调 .cmd 文件需要特殊处理：避免 cmd /c 对 markdown 里的 | / & 等字符的解析。
        # 解决方案：不走 cmd，直接读 .cmd 文件找到 node 路径后调 node。
        if MCPORTER.lower().endswith('.cmd') or MCPORTER.lower().endswith('.bat'):
            # 读 .cmd 文件，提取里面的 node + js 入口
            with open(MCPORTER, 'r', encoding='utf-8', errors='ignore') as f:
                cmd_content = f.read()
            # .cmd 中会包含 node 路径和 js 入口脚本
            # 例: node  "%~dp0\node_modules\mcporter\dist\cli.js"  %*
            import re as _re
            m = _re.search(r'node\s+"([^"]+)"', cmd_content) or _re.search(r'"([^"]+\.js)"', cmd_content)
            if m:
                js_path = m.group(1).replace('%dp0%', os.path.dirname(MCPORTER) + os.sep).replace('%~dp0', os.path.dirname(MCPORTER) + os.sep)
                # 查找 node 可执行文件
                node_exe = shutil.which('node') or os.path.join(os.path.dirname(MCPORTER), 'node.exe')
                if os.path.isfile(node_exe) and os.path.isfile(js_path):
                    full_cmd = [node_exe, js_path] + args[1:]
                else:
                    full_cmd = ['cmd.exe', '/c'] + args
            else:
                full_cmd = ['cmd.exe', '/c'] + args
        else:
            full_cmd = args
        
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=60,
            shell=False,
        )
        out = result.stdout.strip()
        # mcporter 输出可能是文本/JSON 混合，先尝试 JSON parse
        try:
            data = json.loads(out)
            return {'ok': result.returncode == 0, 'data': data, 'raw': out}
        except json.JSONDecodeError:
            return {'ok': result.returncode == 0, 'data': out, 'raw': out, 'stderr': result.stderr}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


if __name__ == '__main__':
    # 测试：读 4018670685
    if len(sys.argv) > 1:
        docid = sys.argv[1]
    else:
        docid = "4018670685"
    
    r = call_iwiki('getDocument', docid=docid)
    print(json.dumps(r, ensure_ascii=False, indent=2)[:2000])
