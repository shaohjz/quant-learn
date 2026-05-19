"""scripts/test_vnpy_qmt.py — 验证 vnpy + QmtGateway 链路最小用例

跑法：
    cd quant-learn
    .venv\\Scripts\\python.exe scripts\\test_vnpy_qmt.py

它会：
1. 加载 gateways/qmt_config.json
2. 起 MainEngine + QmtGateway（dry_run=True）
3. 订阅 600330.SSE 一只股票，等 5 秒看 tick 是否进来
4. 不下任何单
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s | %(message)s")
log = logging.getLogger("test_vnpy_qmt")


def main():
    from vnpy.trader.constant import Exchange
    from vnpy.trader.object import SubscribeRequest
    from apps import build_main_engine

    me, ee, setting = build_main_engine(connect=True, dry_run=True)
    log.info("setting=%s", {k: v for k, v in setting.items() if not k.startswith("_")})

    # 订阅一只
    req = SubscribeRequest(symbol="600330", exchange=Exchange.SSE)
    me.subscribe(req, "QMT")

    log.info("等待 5 秒看是否有 tick / log ...")
    time.sleep(5)

    log.info("关闭 ...")
    me.close()
    log.info("✅ 测试结束")


if __name__ == "__main__":
    main()
