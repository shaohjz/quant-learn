"""\u9a8c\u8bc1 require_support \u95f8\u95e8\u5bf9\u7535\u4fe1\u73b0\u72b6\u7684\u7ed3\u8bba"""
import sys
from pathlib import Path
ROOT = Path(r'C:\Users\Administrator\.openclaw\workspace\quant-learn')
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))

from sim.portfolio import load_all_alert_rules
from sim_executor import _check_trend_gate

rules = load_all_alert_rules()
# \u627e\u7535\u4fe1\u7684 buy_zone \u89c4\u5219
for r in rules:
    if r['code'] == '601728' and 'buy' in r.get('level', ''):
        print(f"\u89c4\u5219: {r['code']} {r['name']} {r['level']} @{r['trigger']}")
        print(f"trend_filter: {r.get('trend_filter')}")
        passed, reason = _check_trend_gate(r, 'BUY_LIGHT')
        print(f"\nBUY_LIGHT: {'\u2705 PASS' if passed else '\u274c BLOCK'}")
        print(f"reason: {reason}")
        print()

# \u540c\u65f6\u62fc\u4e2a\u6d4b\u8bd5\uff1a\u6a21\u62df\u4e00\u4e2a\u91cf\u80fd\u4f01\u7a33+\u542f\u52a8\u4fe1\u53f7\u7684\u573a\u666f
print('\n=== \u4eff\u771f\uff1a\u5982\u679c\u4eca\u65e5\u91cf\u6bd4 1.5 \u4e14\u6536\u7ea2\u4f1a\u600e\u6837? ===')
print('\u53ea\u80fd\u9760\u672a\u6765\u771f\u5b9e\u6570\u636e\u9a8c\u8bc1\u3002\u672c\u811a\u672c\u53ea\u662f\u770b\u73b0\u72b6\u3002')
