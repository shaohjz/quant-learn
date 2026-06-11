import qlib
qlib.init(provider_uri=r'C:\Users\Administrator\.qlib\qlib_data\cn_data', region='cn')
from qlib.data import D
print('test SH000300 close range:')
df = D.features(['SH000300'], ['$close'], start_time='2019-01-01', end_time='2020-09-25', freq='day')
print(df.head())
print('rows=', len(df))
