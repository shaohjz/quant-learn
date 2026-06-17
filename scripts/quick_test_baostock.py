#!/usr/bin/env python3
"""快速测试 BaoStock 连接"""
import threading
import time
import baostock as bs

result = {'success': False, 'logged_in': False, 'error': None}

def login_with_timeout():
    try:
        print('  正在登录 BaoStock...')
        lg = bs.login()
        result['logged_in'] = (lg.error_code == '0')
        result['error'] = lg.error_msg if lg.error_code != '0' else None
        result['success'] = True
    except Exception as e:
        result['error'] = str(e)
        result['success'] = True

print('测试 BaoStock 连接...')
print('=' * 60)

# 启动登录线程
thread = threading.Thread(target=login_with_timeout)
thread.daemon = True
start_time = time.time()
thread.start()

# 等待最多15秒
thread.join(timeout=15)

if thread.is_alive():
    elapsed = time.time() - start_time
    print(f'✗ BaoStock 登录超时（{elapsed:.1f}秒）')
    print('  可能原因：网络连接慢、API限流、或BaoStock服务不可用')
    print('  建议：检查网络、稍后重试、或使用其他数据源')
else:
    if result['success']:
        if result['logged_in']:
            print('✓ BaoStock 登录成功')
            print('  可以正常使用 BaoStock 获取数据')
        else:
            print(f'✗ BaoStock 登录失败: {result["error"]}')
    else:
        print(f'✗ BaoStock 登录异常: {result["error"]}')

bs.logout()
print('=' * 60)
