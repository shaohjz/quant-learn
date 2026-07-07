import sys, logging
logging.basicConfig(level=logging.INFO)
sys.path.insert(0, r'C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts')
from data_source_manager import DataSourceManager

mgr = DataSourceManager()

test_symbols = ['000001', '600330', '000300']
start_date = '20260620'
end_date = '20260626'

print('=== Multi-stock test ===')
for symbol in test_symbols:
    try:
        df = mgr.fetch_data(symbol, start_date, end_date)
        if df is not None and len(df) > 0:
            min_date = df['date'].min().strftime('%Y-%m-%d')
            max_date = df['date'].max().strftime('%Y-%m-%d')
            print(f'  {symbol}: SUCCESS ({len(df)} rows, {min_date} ~ {max_date})')
        else:
            print(f'  {symbol}: FAILED (empty)')
    except Exception as e:
        print(f'  {symbol}: ERROR {type(e).__name__}: {e}')

print()
print('=== Source status ===')
print(mgr.source_status)
