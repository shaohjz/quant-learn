import yaml
cfg = yaml.safe_load(open('config.yaml', encoding='utf-8'))
um = cfg['watchlist']['user_manual']
if '600310' in um:
    print('600310 广西能源 在观察列表中:')
    for k, v in um['600310'].get('rules', {}).items():
        print(f"  {k}: trigger={v.get('trigger')} dir={v.get('dir')}")
    print(f"  name: {um['600310'].get('name')}")
else:
    print('600310 不在 user_manual 中')
    auto = yaml.safe_load(open('config_auto.yaml', encoding='utf-8')) or {}
    ad = auto.get('auto_discovered', {})
    if '600310' in ad:
        print(f"在 auto_discovered 中: {ad['600310']}")
    else:
        print("也不在 auto_discovered 中 - 可能已被清理")
