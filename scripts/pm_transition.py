import os
import re
import sqlite3
import glob
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'data' / 'pm.db'
TEST_REPORTS_DIR = ROOT / 'pm' / 'test_reports'

def process_test_reports():
    if not DB_PATH.exists():
        print('DB not found.')
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # regex to match state transition, e.g., '- REQ-002: testing -> done' or '- BUG-001: fixed -> verified'
    pattern = re.compile(r'-\s*(REQ-\d+|BUG-\d+)[:\s]+`?(testing|in_progress|fixed|open)`?\s*(?:->|到)\s*`?(done|verified|reopened|pending)`?', re.IGNORECASE)
    
    report_files = glob.glob(str(TEST_REPORTS_DIR / '*.md'))
    updates = 0
    
    for report_file in report_files:
        with open(report_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # extract transitions
        for match in pattern.finditer(content):
            task_id = match.group(1).upper()
            from_state = match.group(2).lower()
            to_state = match.group(3).lower()
            
            # check current state in DB
            cursor.execute('SELECT status FROM tasks WHERE id=?', (task_id,))
            row = cursor.fetchone()
            if row:
                current_status = row[0].lower()
                if current_status == from_state:
                    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    cursor.execute('UPDATE tasks SET status=?, updated_at=? WHERE id=?', (to_state, now, task_id))
                    print(f'Updated {task_id}: {from_state} -> {to_state}')
                    updates += 1
                else:
                    print(f'Skipped {task_id}: current status is {current_status}, expected {from_state}.')
            else:
                print(f'Task {task_id} not found in DB.')
                
    if updates > 0:
        conn.commit()
        print(f'Successfully applied {updates} transitions.')
    else:
        print('No status transitions applied.')
        
    conn.close()

if __name__ == '__main__':
    process_test_reports()
