import subprocess, json, base64, sys

mcporter = r'C:\openclaw\openclaw\runtime\node-v22.22.0-win-x64\mcporter.cmd'
md = open(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\output\reviews\2026-05-19.md', encoding='utf-8').read()
b64 = base64.b64encode(md.encode('utf-8')).decode('ascii')
args = {'parent_id': 4018670685, 'filename': 'test_import.md', 'file_content': b64, 'content_encoding': 'base64', 'task_type': 'md_import', 'cover': True}

# 方法 1: cmd /c + 列表
print('=== Method 1: cmd /c + list ===')
r1 = subprocess.run(['cmd.exe', '/c', mcporter, 'call', 'iwiki.importDocument', '--args', json.dumps(args)],
                    capture_output=True, text=True, encoding='utf-8', timeout=60)
print(f'rc={r1.returncode}')
print(f'stdout: {r1.stdout[:500]}')
print(f'stderr: {r1.stderr[:500]}')

# 方法 2: shell=False + .cmd
print('\n=== Method 2: shell=False with .cmd directly ===')
try:
    r2 = subprocess.run([mcporter, 'call', 'iwiki.importDocument', '--args', json.dumps(args)],
                        capture_output=True, text=True, encoding='utf-8', timeout=60, shell=False)
    print(f'rc={r2.returncode}')
    print(f'stdout: {r2.stdout[:500]}')
    print(f'stderr: {r2.stderr[:500]}')
except Exception as e:
    print(f'failed: {e}')
