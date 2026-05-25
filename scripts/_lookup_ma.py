"""Fetch MA5/MA10/MA20 for target stocks via BaoStock."""
import baostock as bs
import pandas as pd
from datetime import datetime, timedelta

bs.login()

stocks = [
    ('sh.600186', '莲花控股'),
    ('sz.002290', '禾盛新材'),
    ('sh.603256', '宏和科技'),
]

end = datetime.now().strftime('%Y-%m-%d')
start = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')

for code, name in stocks:
    rs = bs.query_history_k_data_plus(
        code, "date,close,volume",
        start_date=start, end_date=end,
        frequency="d", adjustflag="2"
    )
    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(rows, columns=rs.fields)
    df['close'] = pd.to_numeric(df['close'], errors='coerce')
    df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
    df.dropna(subset=['close'], inplace=True)

    if len(df) < 20:
        print(f'{code} {name}: 数据不足 ({len(df)} 天)')
        continue

    ma5 = df['close'].rolling(5).mean().iloc[-1]
    ma10 = df['close'].rolling(10).mean().iloc[-1]
    ma20 = df['close'].rolling(20).mean().iloc[-1]
    last = df['close'].iloc[-1]
    high20 = df['close'].tail(20).max()
    low20 = df['close'].tail(20).min()

    print(f'\n{code} {name}')
    print(f'  最近收盘: {last:.2f}')
    print(f'  MA5={ma5:.2f} MA10={ma10:.2f} MA20={ma20:.2f}')
    print(f'  20日高={high20:.2f} 20日低={low20:.2f}')
    # 趋势判断
    trend = 'BULL' if last > ma5 > ma10 > ma20 else ('BEAR' if last < ma20 else 'MIXED')
    print(f'  趋势: {trend}')

bs.logout()
