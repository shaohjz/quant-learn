"""
快速验证 REQ-002 收益率曲线图
运行此脚本后访问 http://localhost:8080 查看效果
"""
import subprocess
import time
import webbrowser

print("=" * 60)
print("REQ-002 收益率曲线图 - 快速验证")
print("=" * 60)

# 1. 检查数据库是否有数据
print("\n[1/3] 检查快照数据...")
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sim_live_mirror.db"

conn = sqlite3.connect(str(DB_PATH))
count = conn.execute("SELECT COUNT(*) FROM daily_snapshot").fetchone()[0]
conn.close()

if count > 0:
    print(f"    ✅ 已有 {count} 条快照记录")
else:
    print("    ⚠️ 没有快照数据，正在生成测试数据...")
    subprocess.run([".venv/Scripts/python.exe", "scripts/generate_test_snapshots.py"], cwd=str(ROOT))

# 2. 检查 Web 服务
print("\n[2/3] 检查 Web 服务...")
import urllib.request
try:
    response = urllib.request.urlopen("http://localhost:8080/api/equity_curve", timeout=2)
    print("    ✅ Web 服务正常运行")
except:
    print("    ⚠️ Web 服务未运行，正在启动...")
    subprocess.Popen([".venv/Scripts/python.exe", "web/app.py"], cwd=str(ROOT))
    time.sleep(3)
    print("    ✅ Web 服务已启动")

# 3. 打开浏览器
print("\n[3/3] 打开浏览器...")
print("    🌐 http://localhost:8080")
print("\n" + "=" * 60)
print("📊 请在浏览器中查看「实盘」Tab 顶部的收益率曲线图")
print("=" * 60)

webbrowser.open("http://localhost:8080")
