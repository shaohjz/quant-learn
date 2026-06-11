import yaml

with open('config.yaml', 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)

wl = cfg.get('watchlist', {})
for code in ['002290', '600186', '603256']:
    info = wl.get(code)
    if info:
        rules = list(info.get('rules', {}).keys())
        print(f"  OK {code} {info['name']} rules={rules}")
    else:
        print(f"  MISS {code}")
