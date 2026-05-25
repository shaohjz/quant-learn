"""Patch portfolio_alert: 推送写入 push_history"""
from pathlib import Path
f = Path('scripts/portfolio_alert.py')
text = f.read_text(encoding='utf-8')

# 在文件头部 import 区域加 sqlite3（可能已有）
if 'import sqlite3' not in text:
    text = text.replace('import sys', 'import sys\nimport sqlite3')

# 找到推送函数调用的地方，在推送后写入DB
# 搜索 push 成功后加一行
old_push = 'logger.info("✓ 企微推送成功")'
new_push = '''logger.info("✓ 企微推送成功")
                    # 保存推送记录
                    try:
                        _conn = sqlite3.connect(str(ROOT / "data" / "sim_live_mirror.db"))
                        _conn.execute("INSERT INTO push_history (push_type, phase, content) VALUES (?,?,?)",
                                      ("alert", "trigger", full_msg))
                        _conn.commit()
                        _conn.close()
                    except Exception:
                        pass'''

if old_push in text:
    text = text.replace(old_push, new_push, 1)  # 只替换第一个
    f.write_text(text, encoding='utf-8')
    print("✓ portfolio_alert patched")
else:
    print("✗ target not found")
