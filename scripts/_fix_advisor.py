"""修复 parse_alert_rules"""
from pathlib import Path

f = Path('scripts/daily_advisor.py')
text = f.read_text(encoding='utf-8')

old = '''    for code, info in stocks.items():
        if not info.get('enabled', True):
            continue
        for rule in info.get('rules', []):
            rules.append({
                'code': code,
                'name': info.get('name', ''),
                'level': rule.get('level', ''),
                'trigger': rule.get('trigger', 0),
                'direction': rule.get('direction', 'below'),
            })
    return rules'''

new = '''    for code, info in stocks.items():
        if not info.get('enabled', True):
            continue
        rules_data = info.get('rules', {})
        if isinstance(rules_data, dict):
            # {level_name: {trigger, dir, msg}} 格式
            for level_name, rule_info in rules_data.items():
                if isinstance(rule_info, dict):
                    rules.append({
                        'code': code,
                        'name': info.get('name', ''),
                        'level': level_name,
                        'trigger': rule_info.get('trigger', 0),
                        'direction': rule_info.get('dir', 'below'),
                    })
        elif isinstance(rules_data, list):
            for rule in rules_data:
                rules.append({
                    'code': code,
                    'name': info.get('name', ''),
                    'level': rule.get('level', ''),
                    'trigger': rule.get('trigger', 0),
                    'direction': rule.get('direction', 'below'),
                })
    return rules'''

text = text.replace(old, new)
f.write_text(text, encoding='utf-8')
print("OK")
