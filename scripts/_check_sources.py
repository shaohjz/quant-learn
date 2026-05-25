import yaml
cfg = yaml.safe_load(open('config.yaml', encoding='utf-8'))
um = cfg['watchlist']['user_manual']
sources = {}
for code, info in um.items():
    s = info.get('source', '未知')
    sources.setdefault(s, []).append(f"{code} {info.get('name','')}: {info.get('added_reason','')}")
for s, stocks in sources.items():
    print(f"\n=== {s} ({len(stocks)}只) ===")
    for st in stocks:
        print(f"  {st}")
