"""apps/intraday_app.py — 通用 vnpy 引擎 wrapper

提供一个 build_main_engine() 工厂，被 runners 复用：
- 加载 gateways/qmt_config.json
- 注册 QmtGateway
- 加载 CtaStrategyApp
- 暴露 main_engine + cta_engine + event_engine
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Tuple

from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine, OmsEngine
from vnpy_ctastrategy import CtaStrategyApp

from gateways import QmtGateway

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]


def load_qmt_setting(path: Path | None = None) -> dict:
    cfg_path = path or (ROOT / "gateways" / "qmt_config.json")
    if not cfg_path.exists():
        raise FileNotFoundError(f"找不到 QMT 配置 {cfg_path}")
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def build_main_engine(connect: bool = True, dry_run: bool = True) -> Tuple[MainEngine, EventEngine, dict]:
    """构建 vnpy 主引擎并注册 QMT gateway。

    :param connect: 是否调用 gateway.connect 立即拉起 xtquant 链路（试跑时 False 可以纯 import 测试）
    :param dry_run: True 时下单不真发（迁移期默认）
    """
    setting = load_qmt_setting()
    setting["dry_run"] = dry_run

    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    main_engine.add_engine(OmsEngine)
    main_engine.add_gateway(QmtGateway)
    main_engine.add_app(CtaStrategyApp)

    if connect:
        main_engine.connect(setting, "QMT")

    return main_engine, event_engine, setting
