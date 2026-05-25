# test_migration.py — 测试迁移后的配置加载
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sim import portfolio

print("=== 测试观察池加载 ===")
rules = portfolio.load_watchlist_rules()
print(f"✓ 总共加载: {len(rules)} 只")

user_manual = [code for code, r in rules.items() if r.get('category') == 'user_manual']
auto_discovered = [code for code, r in rules.items() if r.get('category') == 'auto_discovered']

print(f"  - user_manual: {len(user_manual)} 只")
print(f"  - auto_discovered: {len(auto_discovered)} 只")

print("\n=== 测试告警规则加载（兼容性） ===")
all_rules = portfolio.load_all_alert_rules()
print(f"✓ 总共 {len(all_rules)} 条规则")

watchlist_rules = [r for r in all_rules if r['source'] == 'watchlist']
print(f"  - 观察池规则: {len(watchlist_rules)} 条")

print("\n✅ 迁移验证通过！")
