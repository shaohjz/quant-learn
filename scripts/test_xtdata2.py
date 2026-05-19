import sys
sys.path.insert(0, r"D:\国金QMT交易端模拟\bin.x64\Lib\site-packages")
from xtquant import xtdata

# 试拿全推行情（mini-QMT 行情服务）
try:
    r = xtdata.get_full_tick(["600330.SH"])
    print("get_full_tick:", r)
except Exception as e:
    print(f"ERR: {e}")
