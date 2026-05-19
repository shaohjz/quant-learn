"""runners/run_intraday.py — 盘中盯盘启动器（无 GUI）

用法：
    cd quant-learn
    .venv\\Scripts\\python.exe -m runners.run_intraday          # 默认 dry_run
    .venv\\Scripts\\python.exe -m runners.run_intraday --live   # 真发单（需 QMT 客户端登录）
    .venv\\Scripts\\python.exe -m runners.run_intraday --duration 30  # 仅跑 30 秒（验证用）

启动流程：
1. 构建 vnpy MainEngine + QmtGateway + CtaStrategyApp
2. 为持仓 5 只 + 观察池 5 只 各 add_strategy(ThresholdAlertStrategy)
3. 为非持仓的 CSI300 信号股 add_strategy(FusionStrategy)（可选）
4. init_engine → start_strategy → 阻塞守护
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

# 让 runners.* 能 import 项目根
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps import build_main_engine
from strategies.threshold_alert_strategy import ThresholdAlertStrategy, RULES  # noqa: F401
from strategies.fusion_strategy import FusionStrategy  # noqa: F401


def _vt_symbol(code: str) -> str:
    """6 位代码转 vnpy vt_symbol"""
    if code.startswith(("60", "68", "9")):
        return f"{code}.SSE"
    return f"{code}.SZSE"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", help="真发单（默认 dry_run）")
    p.add_argument("--duration", type=int, default=0,
                   help="跑多少秒后退出，0=守护不退出（盘中模式）")
    p.add_argument("--no-fusion", action="store_true", help="不加载 FusionStrategy")
    return p.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s | %(message)s")
    log = logging.getLogger("run_intraday")

    dry_run = not args.live
    log.info("启动 vnpy 主引擎 dry_run=%s duration=%s", dry_run, args.duration)
    main_engine, event_engine, setting = build_main_engine(connect=True, dry_run=dry_run)

    cta_engine = main_engine.get_engine("CtaStrategy")
    cta_engine.init_engine()
    # 把我们自己的策略模块注册到 cta_engine 的 classes 表
    cta_engine.load_strategy_class_from_module("strategies.threshold_alert_strategy")
    cta_engine.load_strategy_class_from_module("strategies.fusion_strategy")
    log.info("cta_engine 初始化完成 已注册策略类: %s",
             cta_engine.get_all_strategy_class_names())

    # 收集所有需要订阅 + 起策略的股票
    codes_alert = sorted({r["code"] for r in RULES})  # 含持仓 + 观察池
    log.info("阈值策略将覆盖 %d 只股票: %s", len(codes_alert), codes_alert)

    for code in codes_alert:
        vt_sym = _vt_symbol(code)
        sname = f"alert_{code}"
        try:
            cta_engine.add_strategy("ThresholdAlertStrategy", sname, vt_sym, {})
            cta_engine.init_strategy(sname)
            log.info("✅ 初始化策略 %s -> %s", sname, vt_sym)
        except Exception as e:  # noqa: BLE001
            log.error("初始化策略 %s 失败: %s", sname, e)

    # FusionStrategy：只挂在"非持仓"的观察股上（持仓 5 只走人工建议路线，不挂 fusion）
    fusion_codes: list[str] = []
    if not args.no_fusion:
        from decision.fusion_engine import HOLDINGS
        fusion_codes = [c for c in codes_alert if c not in HOLDINGS]
        log.info("Fusion 策略覆盖 %d 只: %s", len(fusion_codes), fusion_codes)
        for code in fusion_codes:
            vt_sym = _vt_symbol(code)
            sname = f"fusion_{code}"
            try:
                cta_engine.add_strategy("FusionStrategy", sname, vt_sym, {})
                cta_engine.init_strategy(sname)
                log.info("✅ 初始化 Fusion %s -> %s", sname, vt_sym)
            except Exception as e:  # noqa: BLE001
                log.warning("初始化 Fusion %s 失败（可继续）: %s", sname, e)

    # 等 init 走完事件循环（vnpy 的 init 是异步的）
    log.info("等待 2 秒 init 完成...")
    time.sleep(2)

    # 统一 start
    for code in codes_alert:
        sname = f"alert_{code}"
        try:
            cta_engine.start_strategy(sname)
        except Exception as e:  # noqa: BLE001
            log.error("启动 %s 失败: %s", sname, e)
    for code in fusion_codes:
        sname = f"fusion_{code}"
        try:
            cta_engine.start_strategy(sname)
        except Exception as e:  # noqa: BLE001
            log.warning("启动 %s 失败: %s", sname, e)

    # 守护
    log.info("===== 引擎运行中 =====")
    stop_flag = {"v": False}

    def _on_sig(*_):
        stop_flag["v"] = True
    try:
        signal.signal(signal.SIGINT, _on_sig)
        signal.signal(signal.SIGTERM, _on_sig)
    except Exception:  # noqa: BLE001
        pass

    started = time.time()
    try:
        while not stop_flag["v"]:
            time.sleep(1)
            if args.duration > 0 and (time.time() - started) >= args.duration:
                log.info("达到 --duration=%s 秒，退出", args.duration)
                break
    finally:
        log.info("关闭 main_engine ...")
        main_engine.close()
        log.info("已关闭")


if __name__ == "__main__":
    main()
