"""补充 config.yaml 中缺少 added_price 的股票
用 BaoStock 查他们 added_at 那天的收盘价"""
import yaml, sys
sys.path.insert(0, '.')
from pathlib import Path

cfg_path = Path('config.yaml')
cfg = yaml.safe_load(cfg_path.read_text(encoding='utf-8'))
um = cfg['watchlist']['user_manual']

missing = []
for code, info in um.items():
    if 'added_price' not in info:
        missing.append((code, info.get('name',''), info.get('added_at','')))

print(f"缺 added_price 的: {len(missing)} 只")
for code, name, dt in missing:
    print(f"  {code} {name} added_at={dt}")

if not missing:
    print("全部已有 added_price")
    sys.exit(0)

# 用 BaoStock 查历史收盘价
import baostock as bs
bs.login()

for code, name, added_at in missing:
    if not added_at:
        continue
    # 转换代码格式
    prefix = 'sh' if code.startswith('6') else 'sz'
    bs_code = f"{prefix}.{code}"
    rs = bs.query_history_k_data_plus(bs_code, "date,close", start_date=str(added_at), end_date=str(added_at), frequency="d")
    row = rs.get_row_data()
    if row and len(row) >= 2:
        close = float(row[1])
        um[code]['added_price'] = close
        print(f"  ✓ {code} {name}: {added_at} 收盘价 = {close}")
    else:
        print(f"  ✗ {code} {name}: 未找到 {added_at} 数据")

bs.logout()

# 写回 config
cfg_path.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding='utf-8')
print("\n✓ config.yaml 已更新")
