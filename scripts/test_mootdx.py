#!/usr/bin/env python3
"""尝试通过 mootdx (通达信) 获取股票数据"""
import traceback

print("=" * 60)
print("mootdx 通达信数据获取测试")
print("=" * 60)

from mootdx.quotes import Quotes

# 尝试不同的服务器地址
servers = [
    ('120.76.88.134', 7709),   # 通达信官方
    ('47.107.75.159', 7709),   # 腾讯云
    ('106.14.95.144', 7709),   # 阿里云
    ('113.105.73.106', 7709),  # 深圳
    ('59.41.99.223', 7709),    # 广州
]

connected = False
client = None

for ip, port in servers:
    try:
        print(f"\n尝试连接 {ip}:{port}...")
        client = Quotes.factory(address=ip, port=port, timeout=5, market='std')
        print(f"  ✓ 连接成功!")
        connected = True
        break
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        continue

if not connected:
    print("\n❌ 所有通达信服务器均无法连接")
    print("可能原因: 内网防火墙阻断了通达信协议端口(7709)")
    exit(1)

# 测试获取数据
print("\n--- 测试获取 K 线数据 ---")
try:
    df = client.bars(symbol='000001', frequency='day', offset=5)
    if df is not None and len(df) > 0:
        print(f"✓ 成功获取 000001 最近 {len(df)} 条K线:")
        print(df.tail(3).to_string())
    else:
        print("返回空数据")
except Exception as e:
    print(f"✗ 获取失败: {e}")
    traceback.print_exc()

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
