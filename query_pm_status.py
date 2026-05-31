import sqlite3
import os
from datetime import datetime

# 连接数据库
db_path = 'data/pm.db'
if not os.path.exists(db_path):
    print('❌ pm.db 不存在')
    exit(1)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print('=== 📊 QuantLearn PM 进度汇报 ===')
print(f'📅 汇报时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
print()

# 1. 需求状态统计
print('=== 📈 需求状态统计 ===')
cursor.execute('SELECT status, COUNT(*) as count FROM tasks WHERE type="story" GROUP BY status')
req_stats = cursor.fetchall()

req_total = 0
req_done = 0
req_testing = 0
req_pending = 0
req_in_progress = 0

for row in req_stats:
    status = row['status']
    count = row['count']
    req_total += count
    print(f'  {status}: {count}')
    
    if status == 'done':
        req_done = count
    elif status == 'testing':
        req_testing = count
    elif status == 'pending':
        req_pending = count
    elif status == 'in_progress':
        req_in_progress = count

print(f'  📊 总计: {req_total} (完成: {req_done}, 测试中: {req_testing}, 待处理: {req_pending}, 进行中: {req_in_progress})')
print()

# 2. Bug 状态统计
print('=== 🐛 Bug 状态统计 ===')
cursor.execute('SELECT status, COUNT(*) as count FROM tasks WHERE type="bug" GROUP BY status')
bug_stats = cursor.fetchall()

bug_total = 0
bug_open = 0
bug_fixed = 0
bug_verified = 0
bug_closed = 0

for row in bug_stats:
    status = row['status']
    count = row['count']
    bug_total += count
    print(f'  {status}: {count}')
    
    if status == 'open':
        bug_open = count
    elif status == 'fixed':
        bug_fixed = count
    elif status == 'verified':
        bug_verified = count
    elif status == 'closed':
        bug_closed = count

print(f'  📊 总计: {bug_total} (开放: {bug_open}, 已修复: {bug_fixed}, 已验证: {bug_verified}, 已关闭: {bug_closed})')
print()

# 3. 检查长时间未更新的任务
print('=== ⏰ 长时间未更新的任务检查 ===')
cursor.execute('SELECT id, title, status, priority, updated_at FROM tasks WHERE status IN ("testing", "fixed") ORDER BY updated_at ASC')
stale_tasks = cursor.fetchall()

if stale_tasks:
    print('  ⚠️ 以下任务状态长时间未更新（超过3天）:')
    for row in stale_tasks:
        updated_at = datetime.strptime(row['updated_at'], '%Y-%m-%d %H:%M:%S')
        days_ago = (datetime.now() - updated_at).days
        
        if days_ago > 3:
            print(f'    ⚠️  {row["id"]} [{row["priority"]}] ({row["status"]}) {row["title"]}')
            print(f'       最后更新: {row["updated_at"]} ({days_ago}天前)')
else:
    print('  ✅ 没有长时间未更新的 testing/fixed 任务')
print()

# 4. 最新测试报告
print('=== 🧪 最新测试报告 ===')
test_reports_dir = 'pm/test_reports'
if os.path.exists(test_reports_dir):
    reports = sorted([f for f in os.listdir(test_reports_dir) if f.startswith('TEST-')], reverse=True)
    if reports:
        latest_report = reports[0]
        print(f'  📄 最新报告: {latest_report}')
        
        # 读取报告内容的前几行
        report_path = os.path.join(test_reports_dir, latest_report)
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()[:15]
                print('  📝 内容预览:')
                for line in lines:
                    print(f'    {line.rstrip()}')
        except:
            print('  ❌ 无法读取报告内容')
    else:
        print('  ❌ 没有找到测试报告')
else:
    print('  ❌ test_reports 目录不存在')
print()

# 5. 最新 Git 提交
print('=== 📝 最新 Git 提交 ===')
import subprocess
try:
    result = subprocess.run(['git', 'log', '--oneline', '-5'], 
                          capture_output=True, text=True, cwd='.')
    if result.returncode == 0:
        commits = result.stdout.strip().split('\n')
        for commit in commits:
            print(f'  {commit}')
    else:
        print('  ❌ 无法获取 Git 提交记录')
except Exception as e:
    print(f'  ❌ Git 命令执行失败: {e}')
print()

# 6. 今日 PM 闭环记录
print('=== 📅 今日 PM 闭环记录 ===')
today = datetime.now().strftime('%Y-%m-%d')
daily_dir = 'pm/daily'

if os.path.exists(daily_dir):
    daily_files = [f for f in os.listdir(daily_dir) if f.startswith(today)]
    if daily_files:
        print(f'  📁 找到 {len(daily_files)} 个今日记录文件:')
        for file in daily_files:
            print(f'    - {file}')
    else:
        print(f'  ❌ 今天 ({today}) 没有 PM 闭环记录')
else:
    print('  ❌ daily 目录不存在')
print()

# 7. 建议的下一步
print('=== 🚀 下一步建议 ===')

suggestions = []

if req_testing > 0:
    suggestions.append(f'⚠️ 有 {req_testing} 个需求处于 testing 状态，建议优先完成测试和验证')

if bug_open > 0:
    suggestions.append(f'🐛 有 {bug_open} 个 open Bug 需要修复')

if bug_fixed > 0:
    suggestions.append(f'✅ 有 {bug_fixed} 个 fixed Bug 需要验证')

if req_pending > 0:
    suggestions.append(f'📋 有 {req_pending} 个 pending 需求可以开始处理')

if not suggestions:
    suggestions.append('✅ 当前没有阻塞项，可以继续推进新需求')

for i, suggestion in enumerate(suggestions, 1):
    print(f'{i}. {suggestion}')
print()

# 8. 统计摘要
print('=== 📊 统计摘要 ===')
print(f'需求: {req_done}/{req_total} 完成, {req_testing} 个测试中, {req_pending} 个待处理')
print(f'Bug: {bug_open} 个开放, {bug_fixed} 个已修复, {bug_verified} 个已验证')

conn.close()