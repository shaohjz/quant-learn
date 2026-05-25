"""测试 calc_trade_plan 的输出效果"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from portfolio_alert import calc_trade_plan, RULES

# 模拟莲花控股触发 buy_zone
code = '600186'
entry_price = 10.74  # MA10 处触发

# 找同一代码的所有规则
all_rules_for_code = [r for r in RULES if r['code'] == code]
triggered_rule = next((r for r in all_rules_for_code if r['level'] == 'buy_zone'), None)

if triggered_rule:
    print(f"=== 模拟触发：{code} 莲花控股 buy_zone @ {entry_price} ===\n")
    plan = calc_trade_plan(code, entry_price, triggered_rule, all_rules_for_code)
    if plan:
        print(plan)
    else:
        print("(无交易计划)")
else:
    print(f"未找到 {code} 的 buy_zone 规则")
    print(f"该代码的规则: {[r['level'] for r in all_rules_for_code]}")

print("\n")

# 再模拟禾盛新材
code2 = '002290'
entry2 = 95.58
all_rules2 = [r for r in RULES if r['code'] == code2]
triggered2 = next((r for r in all_rules2 if r['level'] == 'buy_zone'), None)
if triggered2:
    print(f"=== 模拟触发：{code2} 禾盛新材 buy_zone @ {entry2} ===\n")
    plan2 = calc_trade_plan(code2, entry2, triggered2, all_rules2)
    if plan2:
        print(plan2)
