#!/usr/bin/env python3
"""Push daily report to WeCom"""

import sys
import os

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

try:
    from wecom_webhook import push_markdown
    
    # Read daily report
    report_path = 'pm/daily_report_2026-07-03_final.md'
    with open(report_path, 'r', encoding='utf-8') as f:
        report_content = f.read()
    
    # Push to WeCom
    print("Pushing daily report to WeCom...")
    result = push_markdown(report_content)
    print(f"Push result: {result}")
    print("Daily report pushed successfully!")
    
except Exception as e:
    print(f"Error pushing daily report: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)