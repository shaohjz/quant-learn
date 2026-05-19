"""strategies/fusion_strategy.py — 双账户融合策略（vnpy 版）

把 decision/fusion_engine.py 的 decide() 包成 vnpy CtaTemplate 子类：
- 启动时加载 data/daily_signals.json
- on_tick 用现价 + qlib_signal + threshold_alert 算出 Decision
- 持仓股（HOLDINGS=5 只）→ 只推送企微，**不真下单**（target_account="real_advisor"）
- 非持仓股（CSI300 信号股等）→ 通过 self.buy()/self.sell() 走 vnpy 引擎，由 QmtGateway 真发到 mini 账户

去重逻辑：同一只股票同一交易日只发一次 BUY 或 SELL，避免反复触发。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Optional

try:
    from vnpy_ctastrategy import CtaTemplate
except Exception:  # noqa: BLE001
    CtaTemplate = object  # type: ignore

from notifier import push_text
from decision.fusion_engine import Decision, decide, HOLDINGS  # 保留老引擎逻辑

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
SIGNAL_FILE = ROOT / "data" / "daily_signals.json"
ALERT_STATE_FILE = ROOT / "output" / "alert_state.json"   # 老 portfolio_alert 写的
ALERT_DB_PATH = ROOT / "data" / "alert_fired.db"            # Phase 3 vnpy 写的


def _load_signals() -> dict:
    """加载 daily_signals.json 转 dict[code]=signal"""
    if not SIGNAL_FILE.exists():
        logger.warning("daily_signals.json 不存在，融合策略将无 qlib 信号")
        return {}
    try:
        data = json.loads(SIGNAL_FILE.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.error("解析 daily_signals.json 失败: %s", e)
        return {}
    out: dict = {}
    for sig in data.get("signals", []) or []:
        code = sig.get("code") or sig.get("stock_code")
        if code:
            out[str(code)] = sig
    return out


# Phase 4: 加载当日 alert 状态（来源：老 alert_state.json + vnpy alert_fired SQLite）
# 返回结构：{code: {level, price, trigger, triggered_at, source}}
def _load_alert_state(today: date) -> dict:
    out: dict = {}
    today_iso = today.isoformat()

    # 1) 老 portfolio_alert.py 的 alert_state.json
    if ALERT_STATE_FILE.exists():
        try:
            data = json.loads(ALERT_STATE_FILE.read_text(encoding="utf-8"))
            day_block = data.get(today_iso) or {}
            for combo_key, info in day_block.items():
                # combo_key 形如 '002342_deep_drop'
                if "_" not in combo_key:
                    continue
                code, level = combo_key.split("_", 1)
                # 取最新触发的 level（同一股票多 level 时保留 "卖出优先级最高" 的）
                cur = out.get(code)
                new_entry = {
                    "level": level,
                    "price": info.get("price"),
                    "trigger": info.get("trigger"),
                    "triggered_at": info.get("triggered_at"),
                    "source": "alert_state.json",
                    "message": info.get("message", ""),
                }
                if cur is None or _level_priority(level) > _level_priority(cur["level"]):
                    out[code] = new_entry
        except Exception as e:  # noqa: BLE001
            logger.warning("读取 alert_state.json 失败: %s", e)

    # 2) vnpy 时代写的 alert_fired SQLite（Phase 3）
    if ALERT_DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(ALERT_DB_PATH), timeout=10)
            rows = conn.execute(
                "SELECT stock_code, level, fired_at, price, trigger_v "
                "FROM alert_fired WHERE trade_date=?", (today_iso,),
            ).fetchall()
            conn.close()
            for code, level, fired_at, price, trigger_v in rows:
                cur = out.get(code)
                new_entry = {
                    "level": level,
                    "price": price,
                    "trigger": trigger_v,
                    "triggered_at": fired_at,
                    "source": "alert_fired.db",
                }
                if cur is None or _level_priority(level) > _level_priority(cur["level"]):
                    out[code] = new_entry
        except Exception as e:  # noqa: BLE001
            logger.warning("读取 alert_fired.db 失败: %s", e)

    return out


def _level_priority(level: Optional[str]) -> int:
    """决策时同一股票多个 level 谁优先（数字越大越优先）"""
    if not level:
        return 0
    if level in ("hard_stop", "stop_loss", "stop_loss_tight", "deep_drop",
                 "limitdown_open", "trend_break"):
        return 100
    if level in ("take_profit", "take_profit_half"):
        return 80
    if level in ("half_out", "rebound_exit", "yc_exit"):
        return 60
    if level in ("buy_strong",):
        return 50
    if level in ("buy_zone",):
        return 40
    return 10


class FusionStrategy(CtaTemplate):
    """融合策略，每个 vnpy 实例对应一只股票。

    Variables:
      last_decision: 最近一次 decide() 输出的 reason
      decisions_today: 今日已下达的 actionable 决策数
    """

    author = "quant-learn-vnpy"
    parameters: list = []
    variables: list = ["last_price", "decisions_today", "last_action"]

    def __init__(self, cta_engine, strategy_name: str, vt_symbol: str, setting: dict):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self._symbol = vt_symbol.split(".")[0]
        self.last_price: float = 0.0
        self.last_action: str = "NONE"
        self.decisions_today: int = 0
        self._today: date = date.today()
        # 同一交易日同动作只发一次
        self._fired_action: set[str] = set()
        self._signals: dict = {}
        self._alert_state: dict = {}  # Phase 4: {code: alert_dict}

    # ---------- 生命周期 ----------
    def on_init(self):
        self._signals = _load_signals()
        self._alert_state = _load_alert_state(self._today)
        sig = self._signals.get(self._symbol)
        my_alert = self._alert_state.get(self._symbol)
        self.write_log(
            f"FusionStrategy 初始化 {self._symbol} 持仓股={self._symbol in HOLDINGS} "
            f"qlib_signal={'有' if sig else '无'} "
            f"alert={my_alert.get('level') if my_alert else '无'}"
        )

    def on_start(self):
        self.write_log("策略启动")

    def on_stop(self):
        self.write_log("策略停止")

    def on_tick(self, tick):
        if tick is None or tick.last_price is None:
            return
        # 跨天重置
        today = date.today()
        if today != self._today:
            self._today = today
            self._fired_action.clear()
            self.decisions_today = 0
            self._signals = _load_signals()
            self._alert_state = _load_alert_state(self._today)

        price = float(tick.last_price)
        self.last_price = price
        self._handle(price)

    def on_bar(self, bar):
        if bar is None:
            return
        self._handle(float(bar.close_price))

    # ---------- 决策 + 执行 ----------
    def _handle(self, price: float):
        if price <= 0:
            return
        sig = self._signals.get(self._symbol)
        # Phase 4: 把当日 alert 状态作为 threshold_alert 输入喂给 decide()
        # 来源：alert_state.json (老 portfolio_alert) + alert_fired.db (vnpy ThresholdAlertStrategy)
        threshold_alert = self._alert_state.get(self._symbol)
        # 每隔 100 tick 重新读一次（覆盖盘中刚触发的）
        self._tick_counter = getattr(self, "_tick_counter", 0) + 1
        if self._tick_counter % 100 == 0:
            self._alert_state = _load_alert_state(self._today)
            threshold_alert = self._alert_state.get(self._symbol)
        decision: Decision = decide(
            stock_code=self._symbol,
            current_price=price,
            position_qty=int(getattr(self, "pos", 0) or 0),
            qlib_signal=sig,
            threshold_alert=threshold_alert,
        )
        # 提高 confidence：阈值刚触发 + AI 看法一致 → 加成 0.1（封顶 0.95）
        if threshold_alert and sig:
            alert_lvl = threshold_alert.get("level")
            ai_action = sig.get("action")
            buy_aligned = (alert_lvl in ("buy_zone", "buy_strong") and ai_action == "BUY")
            sell_aligned = (alert_lvl in ("stop_loss", "stop_loss_tight", "hard_stop",
                                          "take_profit", "deep_drop")
                            and ai_action == "SELL")
            if (buy_aligned or sell_aligned) and decision.is_actionable():
                old = decision.confidence
                decision.confidence = min(0.95, decision.confidence + 0.10)
                decision.reason += f" [boost: alert+AI 共识 conf {old:.2f}→{decision.confidence:.2f}]"

        if not decision.is_actionable():
            return

        if decision.action in self._fired_action:
            return  # 同动作今日已发
        self._fired_action.add(decision.action)
        self.decisions_today += 1
        self.last_action = decision.action

        msg = (
            f"[Fusion {self._symbol}] {decision.action} qty={decision.qty} "
            f"px={decision.price:.2f} target={decision.target_account} "
            f"rule={decision.rule}\n{decision.reason}"
        )
        self.write_log(msg)

        # 持仓股：只推送，不下单
        if decision.target_account == "real_advisor":
            push_text("📣 [人工建议] " + msg)
            return

        # qmt_sim：通过 vnpy 引擎下单（dry_run 由 gateway 控制）
        push_text("🤖 [自动执行] " + msg)
        try:
            if decision.action == "BUY":
                self.buy(price=decision.price, volume=decision.qty)
            elif decision.action == "SELL":
                self.sell(price=decision.price, volume=decision.qty)
        except Exception as e:  # noqa: BLE001
            self.write_log(f"下单异常: {e}")
