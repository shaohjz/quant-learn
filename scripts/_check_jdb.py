import yaml
cfg = yaml.safe_load(open('config.yaml', encoding='utf-8'))
jdb = cfg['watchlist']['user_manual'].get('000725', {})
print('京东方配置:')
for k, v in jdb.items():
    print(f'  {k}: {v}')
