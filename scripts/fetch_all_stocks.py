#!/usr/bin/env python3
"""
fetch_all_stocks.py - 数据拉取入口（自动路由到最新版本）

当前版本：v3（支持离线模式 + 本地缓存兜底）
- 内网环境所有外部数据源不可达时，自动使用 data/*.csv 本地缓存
- 设置 USE_CACHE_ONLY=true 强制离线模式
- Zscaler SSL 拦截自动检测

历史版本：
- v1: 原始版本（已废弃）
- v2: BaoStock 主力 + AKShare 备选（仍受网络限制）
- v3: 离线模式 + 本地缓存兜底（当前生产版本）
"""
import sys
import os

# 路由到 v3（当前生产版本）
_v3_path = os.path.join(os.path.dirname(__file__), 'fetch_all_stocks_v3.py')
if not os.path.exists(_v3_path):
    print(f"[错误] {_v3_path} 不存在，请联系运维", file=sys.stderr)
    sys.exit(1)

print(f"[信息] 使用 fetch_all_stocks_v3.py（离线模式支持）", file=sys.stderr)
sys.argv.insert(0, _v3_path)
os.execv(sys.executable, [sys.executable] + sys.argv)
