#!/usr/bin/env python3
"""
测试 QMT 连接
"""
import sys
import os

# 添加 QMT Python 路径
qmt_python_path = r"D:\国金QMT交易端模拟\bin.x64\Lib\site-packages"
qmt_bin_path = r"D:\国金QMT交易端模拟\bin.x64"
if qmt_python_path not in sys.path:
    sys.path.insert(0, qmt_python_path)
    
    # 也添加 bin.x64 到 PATH（某些 DLL 可能需要）
    os.environ['PATH'] = qmt_bin_path + os.pathsep + os.environ.get('PATH', '')

try:
    from xtquant import xtdata
    print("[成功] xtquant 模块导入成功")
    
    # 测试连接
    print("测试 QMT 连接...")
    
    # 尝试获取上证指数数据来测试连接
    test_code = "000001.SH"
    print(f"尝试获取 {test_code} 行情数据...")
    
    # 获取最新行情
    tick = xtdata.get_local_data(field_list=['lastPrice'], stock_list=[test_code], period='tick', count=1)
    
    if tick and test_code in tick.get('lastPrice', {}):
        print(f"[成功] QMT 连接正常，获取到 {test_code} 最新价: {tick['lastPrice'][test_code]}")
    else:
        print("[警告] QMT 已启动但无法获取行情数据，可能需要登录或等待数据加载")
        print(f"返回数据: {tick}")
    
except ImportError as e:
    print(f"[错误] 无法导入 xtquant 模块: {e}")
    print("请检查 QMT 安装路径和 Python 环境配置")
    sys.exit(1)
except Exception as e:
    print(f"[错误] QMT 连接测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
