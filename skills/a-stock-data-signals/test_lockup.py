import sys
sys.path.insert(0, '.')
from a_stock_data_signals import lockup_warning_signal

codes = ['000301', '603260', '603290', '600703', '000708']
for code in codes:
    try:
        r = lockup_warning_signal(code)
        if r.get('has_upcoming'):
            print(f'{code}: WARNING has lockup!')
            for u in r['upcoming'][:3]:
                print(f'  {u["date"]} {u["type"]} shares={u["shares"]}')
        else:
            print(f'{code}: OK no lockup')
    except Exception as e:
        print(f'{code}: ERROR {e}')
