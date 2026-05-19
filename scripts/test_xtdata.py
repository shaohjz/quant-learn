import sys
sys.path.insert(0, r"D:\国金QMT交易端模拟\bin.x64\Lib\site-packages")
try:
    from xtquant import xtdata
    print("xtdata imported")
    # 尝试拿一个标的最新行情（不需要登录交易端）
    r = xtdata.get_full_tick(["600330.SH", "002709.SZ"])
    print("xtdata.get_full_tick:", r)
except Exception as e:
    print(f"xtdata error: {type(e).__name__}: {e}")
