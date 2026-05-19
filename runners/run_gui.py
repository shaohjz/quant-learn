"""runners/run_gui.py — 启动 vnpy 桌面 GUI（PySide6）

用法：
    cd quant-learn
    .venv\\Scripts\\python.exe -m runners.run_gui

注意：
  - 这是 Qt 桌面端，需要 Windows 桌面会话 / RDP，纯 SSH 跑不起来
  - 默认 dry_run，进入 GUI 后再手工 add_strategy 也可以
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from vnpy.event import EventEngine
    from vnpy.trader.engine import MainEngine
    from vnpy.trader.ui import MainWindow, create_qapp
    from vnpy_ctastrategy import CtaStrategyApp

    from gateways import QmtGateway

    qapp = create_qapp()

    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    main_engine.add_gateway(QmtGateway)
    main_engine.add_app(CtaStrategyApp)

    main_window = MainWindow(main_engine, event_engine)
    main_window.showMaximized()

    qapp.exec()


if __name__ == "__main__":
    main()
