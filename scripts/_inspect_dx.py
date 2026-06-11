import baostock as bs
import pandas as pd
from datetime import datetime, timedelta

bs.login()
try:
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=120)).strftime('%Y-%m-%d')
    rs = bs.query_history_k_data_plus('sh.601728', 'date,close,low,volume',
                                       start_date=start, end_date=end,
                                       frequency='d', adjustflag='2')
    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(rows, columns=rs.fields)
    for c in ['close','low','volume']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna()
    
    last = df['close'].iloc[-1]
    low60 = df['low'].tail(60).min()
    low20 = df['low'].tail(20).min()
    ma60 = df['close'].tail(60).mean()
    ma20 = df['close'].tail(20).mean()
    ma10 = df['close'].tail(10).mean()
    avg_vol5 = df['volume'].tail(5).mean()
    avg_vol20 = df['volume'].tail(20).mean()
    today_vol = df['volume'].iloc[-1]
    
    print(f'\u4e2d\u56fd\u7535\u4fe1 \u8fd1\u51b5:')
    print(f'  \u73b0\u4ef7        last  = \u00a5{last:.2f}')
    print(f'  MA10              = \u00a5{ma10:.2f}')
    print(f'  MA20              = \u00a5{ma20:.2f}')
    print(f'  MA60              = \u00a5{ma60:.2f}')
    print(f'  \u8fd1 60 \u65e5\u6700\u4f4e   = \u00a5{low60:.2f}')
    print(f'  \u8fd1 20 \u65e5\u6700\u4f4e   = \u00a5{low20:.2f}')
    print(f'  \u4eca\u65e5\u91cf       = {today_vol:,.0f}')
    print(f'  5 \u65e5\u5747\u91cf     = {avg_vol5:,.0f}')
    print(f'  20 \u65e5\u5747\u91cf    = {avg_vol20:,.0f}')
    print(f'  \u4eca\u65e5/5\u65e5\u5747 = {today_vol/avg_vol5:.2f}')
    print(f'  \u4eca\u65e5/20\u65e5\u5747= {today_vol/avg_vol20:.2f}')
    
    print()
    print(f'  \u73b0\u4ef7 \u8ddd MA60     = {(last-ma60)/ma60*100:+.1f}%')
    print(f'  \u73b0\u4ef7 \u8ddd \u8fd1 60 \u65e5\u6700\u4f4e = {(last-low60)/low60*100:+.1f}%')
    
    print()
    print(f'  \u8fd1 10 \u65e5\u8d70\u52bf:')
    for _, row in df.tail(10).iterrows():
        print(f'    {row["date"]} close={row["close"]:.2f} low={row["low"]:.2f} vol={row["volume"]:,.0f}')
finally:
    bs.logout()
