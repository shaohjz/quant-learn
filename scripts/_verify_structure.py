import sys; sys.path.insert(0, '.')
from sim.portfolio import load_all_alert_rules, load_watchlist_rules

all_rules = load_all_alert_rules()
print(f"load_all_alert_rules: {len(all_rules)} rules")
for r in all_rules[:3]:
    print(f"  {r['code']} {r['name']} {r['level']} cat={r.get('category','?')}")
print("  ...")

um = load_watchlist_rules(category='user_manual')
print(f"user_manual watchlist: {len(um)} rules")

ad = load_watchlist_rules(category='auto_discovered')
print(f"auto_discovered watchlist: {len(ad)} rules (empty is OK)")
