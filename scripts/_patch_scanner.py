"""Patch intraday_scanner.py to remove akshare dependency"""
from pathlib import Path
import re

f = Path('scripts/intraday_scanner.py')
text = f.read_text(encoding='utf-8')

# 1. Replace get_universe
old_get_universe = '''def get_universe():
    """获取股票池：沪深300 + 中证500"""
    import akshare as ak
    codes = set()
    try:
        df_300 = ak.index_stock_cons(symbol="000300")
        codes.update(df_300["品种代码"].astype(str).tolist())
        logger.info(f"沪深300: {len(df_300)} 只")
    except Exception as e:
        logger.warning(f"拉沪深300 失败: {e}")
    
    try:
        df_500 = ak.index_stock_cons(symbol="000905")
        codes.update(df_500["品种代码"].astype(str).tolist())
        logger.info(f"中证500: {len(df_500)} 只")
    except Exception as e:
        logger.warning(f"拉中证500 失败: {e}")
    
    return sorted(codes)'''

new_get_universe = '''UNIVERSE_CACHE = ROOT / "data" / "universe_cache.json"

def get_universe():
    """获取股票池：从本地缓存读取（由 BaoStock 每周生成）"""
    if UNIVERSE_CACHE.exists():
        try:
            data = json.loads(UNIVERSE_CACHE.read_text(encoding='utf-8'))
            codes = data.get('codes', [])
            if len(codes) > 100:
                logger.info(f"股票池(缓存): {len(codes)} 只")
                return codes
        except Exception:
            pass
    
    # 缓存不存在时尝试 BaoStock 拉取
    try:
        import baostock as bs
        bs.login()
        codes = set()
        rs = bs.query_hs300_stocks()
        while rs.error_code == '0' and rs.next():
            codes.add(rs.get_row_data()[1].replace('sh.','').replace('sz.',''))
        rs = bs.query_zz500_stocks()
        while rs.error_code == '0' and rs.next():
            codes.add(rs.get_row_data()[1].replace('sh.','').replace('sz.',''))
        bs.logout()
        logger.info(f"股票池(BaoStock): {len(codes)} 只")
        # 保存缓存
        UNIVERSE_CACHE.write_text(json.dumps({
            'codes': sorted(codes), 'updated': datetime.now().isoformat(), 'count': len(codes)
        }, ensure_ascii=False), encoding='utf-8')
        return sorted(codes)
    except Exception as e:
        logger.error(f"BaoStock 拉取失败: {e}")
        return []'''

if old_get_universe in text:
    text = text.replace(old_get_universe, new_get_universe)
    print("✓ get_universe replaced")
else:
    print("✗ get_universe not found (may already be patched)")

# 2. Replace fetch_all_realtime
old_fetch_start = 'def fetch_all_realtime():\n    """拉取全市场实时行情（优先东财，失败后新浪）"""'
old_fetch_end = '    raise RuntimeError("东财和新浪实时行情接口均失败")'

new_fetch = '''def fetch_all_realtime():
    """拉取全市场实时行情（纯新浪HTTP，不依赖akshare）"""
    import re as _re
    import requests
    import pandas as pd
    
    universe = get_universe()
    if not universe:
        raise RuntimeError("股票池为空")
    
    # 转新浪代码格式
    sina_codes = []
    for code in universe:
        if code.startswith(('60', '68', '11', '5')):
            sina_codes.append('sh' + code)
        else:
            sina_codes.append('sz' + code)
    
    # 批量拉取（每批 80 只）
    all_data = []
    headers = {'Referer': 'https://finance.sina.com.cn'}
    batch_size = 80
    
    for i in range(0, len(sina_codes), batch_size):
        batch = sina_codes[i:i+batch_size]
        url = 'https://hq.sinajs.cn/list=' + ','.join(batch)
        try:
            r = requests.get(url, headers=headers, timeout=15)
            r.encoding = 'gbk'
            for line in r.text.strip().split('\\n'):
                m = _re.search(r'hq_str_(s[hz])(\\d+)="(.+?)"', line)
                if not m:
                    continue
                code = m.group(2)
                parts = m.group(3).split(',')
                if len(parts) < 10 or not parts[3]:
                    continue
                try:
                    price = float(parts[3])
                    yclose = float(parts[2])
                    high = float(parts[4])
                    low = float(parts[5])
                    volume = float(parts[8])
                    amount = float(parts[9])
                except (ValueError, IndexError):
                    continue
                if price <= 0 or yclose <= 0:
                    continue
                all_data.append({
                    '代码': code,
                    '名称': parts[0],
                    '最新价': price,
                    '昨收': yclose,
                    '最高': high,
                    '最低': low,
                    '涨跌幅': (price - yclose) / yclose * 100,
                    '成交量': volume,
                    '成交额': amount,
                })
        except Exception as e:
            logger.warning(f"新浪批次 {i//batch_size} 失败: {e}")
            time.sleep(0.3)
    
    if not all_data:
        raise RuntimeError("新浪实时行情拉取失败")
    
    df = pd.DataFrame(all_data)
    logger.info(f"实时行情(新浪): {len(df)} 条")
    return df'''

# Find and replace fetch_all_realtime
start_idx = text.find(old_fetch_start)
end_idx = text.find(old_fetch_end)
if start_idx >= 0 and end_idx >= 0:
    end_idx += len(old_fetch_end)
    text = text[:start_idx] + new_fetch + text[end_idx:]
    print("✓ fetch_all_realtime replaced")
else:
    print(f"✗ fetch_all_realtime not found (start={start_idx}, end={end_idx})")

f.write_text(text, encoding='utf-8')
print("✓ File saved")
