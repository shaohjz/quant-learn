"""
批量将绿电板块股票加入 watchlist.user_manual
来源：泛舟财海 (@Blazing_Sun1) 2026-05-27 推荐
"""
import baostock as bs
import pandas as pd
import yaml
from datetime import datetime, timedelta
from pathlib import Path

# 12 只绿电股
STOCKS = [
    ('301120', '新特电气'),
    ('301179', '泽宇智能'),
    ('600021', '上海电力'),
    ('000600', '建投能源'),
    ('002067', '景兴纸业'),
    ('000899', '赣能股份'),
    ('001896', '豫能控股'),
    ('600310', '广西能源'),
    ('601222', '林洋能源'),
    ('600863', '华能蒙电'),
    ('601991', '大唐发电'),
    ('603693', '江苏新能'),
]

CONFIG_PATH = Path(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\config.yaml')


def code_with_prefix(code: str) -> str:
    if code.startswith('6'):
        return f'sh.{code}'
    return f'sz.{code}'


def fetch_kline(code: str, days: int = 60):
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=days*2)).strftime('%Y-%m-%d')
    rs = bs.query_history_k_data_plus(
        code_with_prefix(code),
        'date,close',
        start_date=start, end_date=end,
        frequency='d', adjustflag='2'
    )
    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(rows, columns=rs.fields)
    df['close'] = pd.to_numeric(df['close'], errors='coerce')
    df = df.dropna()
    return df


def calc_levels(df: pd.DataFrame):
    last = float(df['close'].iloc[-1])
    ma10 = float(df['close'].rolling(10).mean().iloc[-1])
    ma20 = float(df['close'].rolling(20).mean().iloc[-1])
    # ATR proxy: 20 日收盘标准差 * 1.5
    std20 = float(df['close'].rolling(20).std().iloc[-1])
    trend_break = round(ma20 - 1.5 * std20, 2)
    return {
        'last': round(last, 2),
        'ma10': round(ma10, 2),
        'ma20': round(ma20, 2),
        'trend_break': trend_break,
    }


def build_entry(code: str, name: str, levels: dict):
    return {
        'name': name,
        'enabled': True,
        'source': '泛舟财海(@Blazing_Sun1)',
        'recommended_by': '泛舟财海',
        'added_at': '2026-05-27',
        'added_price': levels['last'],
        'added_reason': '泛舟财海推荐绿色电力板块',
        'tags': ['绿电', '电力'],
        'rules': {
            'buy_zone': {
                'trigger': levels['ma10'],
                'dir': 'below',
                'msg': f"💰 {name} BuyZone 阈值 {levels['ma10']:.2f}（前收 MA10），试探建仓",
            },
            'buy_strong': {
                'trigger': levels['ma20'],
                'dir': 'below',
                'msg': f"💰💰 {name} BuyStrong 阈值 {levels['ma20']:.2f}（前收 MA20），优质建仓区",
            },
            'trend_break': {
                'trigger': levels['trend_break'],
                'dir': 'below',
                'msg': f"⚠️ {name}破 {levels['trend_break']:.2f}！跌破 MA20-1.5ATR，趋势可能反转",
            },
        },
    }


def main():
    print('Loading config.yaml...')
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding='utf-8'))
    wm = cfg['watchlist']['user_manual']

    print('Logging into BaoStock...')
    bs.login()
    try:
        added = []
        skipped = []
        for code, name in STOCKS:
            if code in wm:
                print(f'  - SKIP {code} {name} (already in watchlist)')
                skipped.append((code, name))
                continue
            try:
                df = fetch_kline(code)
                if len(df) < 20:
                    print(f'  - WARN {code} {name} insufficient data ({len(df)} rows)')
                    continue
                lv = calc_levels(df)
                wm[code] = build_entry(code, name, lv)
                print(f'  + ADD  {code} {name}: last={lv["last"]} MA10={lv["ma10"]} MA20={lv["ma20"]} TB={lv["trend_break"]}')
                added.append((code, name, lv))
            except Exception as e:
                print(f'  - ERROR {code} {name}: {e}')
    finally:
        bs.logout()

    print(f'\nWriting back: +{len(added)} new, {len(skipped)} skipped')
    CONFIG_PATH.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding='utf-8'
    )
    print('Done.')

    # 摘要
    print('\n=== Summary ===')
    for code, name, lv in added:
        print(f'  {code} {name:6s}  现价 {lv["last"]:>7.2f}  MA10 {lv["ma10"]:>7.2f}  MA20 {lv["ma20"]:>7.2f}  破位 {lv["trend_break"]:>7.2f}')
    if skipped:
        print('Skipped:')
        for code, name in skipped:
            print(f'  {code} {name}')


if __name__ == '__main__':
    main()
