"""\u9a8c\u8bc1 trend_filter \u62e6\u622a\u903b\u8f91"""
import sys
from pathlib import Path
ROOT = Path(r'C:\Users\Administrator\.openclaw\workspace\quant-learn')
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))

# \u52a0\u8f7d\u5e73\u94fa\u540e\u7684 RULES
from sim.portfolio import load_all_alert_rules
rules = load_all_alert_rules()
print(f'Total rules: {len(rules)}')

# \u8fc7\u6ee4\u51fa\u5e26 trend_filter \u7684
print('\n=== \u5305\u542b trend_filter \u7684 buy \u89c4\u5219 ===')
seen = {}
for r in rules:
    if 'buy' not in r.get('level', ''):
        continue
    code = r['code']
    if code in seen:
        continue
    seen[code] = True
    tf = r.get('trend_filter', {})
    abd = r.get('auto_buy_disabled', False)
    print(f"  {code} {r['name']:6s} | level={r['level']:12s} | gate={tf.get('gate','auto'):12s} | status={tf.get('status','?'):8s} | abd={abd}")

# \u9a8c\u8bc1 _check_trend_gate
print('\n=== \u62e6\u622a\u9a8c\u8bc1 ===')
from sim_executor import _check_trend_gate

# \u9009\u51e0\u4e2a\u5178\u578b case
test_cases = [code for code in seen.keys()]
for r in rules:
    if r['code'] not in test_cases or 'buy' not in r.get('level',''):
        continue
    if test_cases.count(r['code']) <= 0:
        continue
    test_cases.remove(r['code'])
    passed, reason = _check_trend_gate(r, 'BUY_LIGHT')
    print(f"  {r['code']} {r['name']:6s} ({r['level']:12s}) BUY_LIGHT: {'\u2705 PASS' if passed else '\u274c BLOCK'} | {reason}")
