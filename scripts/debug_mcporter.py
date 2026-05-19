import sys, os, shutil, re
sys.path.insert(0, r'C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts')
from iwiki_helper import MCPORTER

print(f'MCPORTER={MCPORTER}')
with open(MCPORTER, 'r', encoding='utf-8', errors='ignore') as f:
    cmd_content = f.read()

# 匹配 .cmd 中 node 调用的 .js 入口
m = re.search(r'node\s+"([^"]+)"', cmd_content) or re.search(r'"([^"]+\.js)"', cmd_content)
print(f'regex match: {m.group(1) if m else None}')
if m:
    js_path = m.group(1).replace('%~dp0', os.path.dirname(MCPORTER) + os.sep)
    print(f'js_path={js_path}, exists={os.path.isfile(js_path)}')

node_exe = shutil.which('node')
print(f'node_exe (which)={node_exe}')
node_local = os.path.join(os.path.dirname(MCPORTER), 'node.exe')
print(f'node_local={node_local}, exists={os.path.isfile(node_local)}')
