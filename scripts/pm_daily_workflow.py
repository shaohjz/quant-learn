import os
import sys
import glob
import re
import sqlite3
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'data' / 'pm.db'
TEST_REPORTS_DIR = ROOT / 'pm' / 'test_reports'
DAILY_DIR = ROOT / 'pm' / 'daily'
DAILY_DIR.mkdir(parents=True, exist_ok=True)

def apply_state_transitions():
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    pattern = re.compile(r'-\s*(REQ-\d+|BUG-\d+)[:\s]+`?(testing|fixed)`?\s*(?:->|到)\s*`?(done|verified|reopened)`?', re.IGNORECASE)
    report_files = glob.glob(str(TEST_REPORTS_DIR / '*.md'))
    
    transitions = []
    
    for report_file in report_files:
        with open(report_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
        for match in pattern.finditer(content):
            task_id = match.group(1).upper()
            from_state = match.group(2).lower()
            to_state = match.group(3).lower()
            
            cursor.execute('SELECT status, title FROM tasks WHERE id=?', (task_id,))
            row = cursor.fetchone()
            if row:
                current_status = row[0].lower()
                title = row[1]
                if current_status == from_state:
                    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    cursor.execute('UPDATE tasks SET status=?, updated_at=? WHERE id=?', (to_state, now, task_id))
                    transitions.append(f'- {title}: {from_state} -> {to_state}')
    
    if transitions:
        conn.commit()
    conn.close()
    return transitions

def generate_daily_report(transitions):
    today = date.today().isoformat()
    report_path = DAILY_DIR / f'{today}_workflow.md'
    
    lines = [
        f'# {today} 每日研发闭环自动执行',
        '',
        '## 1. 状态扭转'
    ]
    
    if transitions:
        lines.extend(transitions)
    else:
        lines.append('无需要扭转的状态。')
        
    lines.extend([
        '',
        '## 2. 新需求生成',
        '（待需求 Agent 读取今天日志后自动生成，此处仅为框架）',
        '',
        '## 3. 未解决阻塞',
        '（待 PM Agent 梳理更新）'
    ])
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
        
    print(f'Generated daily report: {report_path}')

def main():
    print('Starting Daily PM Workflow...')
    transitions = apply_state_transitions()
    for t in transitions:
        print(f'Applied transition: {t}')
        
    generate_daily_report(transitions)
    print('Daily PM Workflow finished.')

if __name__ == '__main__':
    main()
