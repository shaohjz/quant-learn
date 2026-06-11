import yaml
cfg = yaml.safe_load(open('config.yaml', encoding='utf-8'))
wl = cfg.get('watchlist', {})
um = wl.get('user_manual', {})
first_key = list(um.keys())[0]
v = um[first_key]
print(f"key: {first_key}")
print(f"type(rules): {type(v.get('rules', []))}")
rules = v.get('rules', [])
if rules:
    print(f"type(rules[0]): {type(rules[0])}")
    print(f"rules[0]: {rules[0]}")
    print(f"rules[:3]: {rules[:3]}")
