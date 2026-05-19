"""strategies/threshold_alert_strategy.py — vnpy 版盘中阈值提醒策略

功能等价于老版 `scripts/portfolio_alert.py`：
- 用 RULES（持仓 + 观察池的价格阈值）在 on_tick 里实时判定
- 命中时调 self.write_log() + notifier.push_text 推到企微
- 同一阈值同一交易日只触发一次

去重持久化（Phase 3 完成）：
- 用 SQLite 表 `alert_fired (trade_date, stock_code, level, fired_at)` 存已触发记录
- 启动时加载当日记录到 self._fired，进程重启不会重复推
- 跨日时清空内存集 + 自动清理 N 天前的数据库行
- DB 路径默认 data/alert_fired.db，可通过环境变量 ALERT_DB_PATH 覆盖
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# CtaTemplate 依赖（仅在 vnpy 环境跑得通）
try:
    from vnpy_ctastrategy import CtaTemplate
    from vnpy.trader.object import TickData, BarData
except Exception:  # noqa: BLE001
    CtaTemplate = object  # type: ignore
    TickData = Any  # type: ignore
    BarData = Any  # type: ignore

from notifier import push_text


# ====================================================================
# 持久化去重存储（Phase 3）
# ====================================================================
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _PROJECT_ROOT / "data" / "alert_fired.db"
ALERT_DB_PATH = Path(os.environ.get("ALERT_DB_PATH", str(_DEFAULT_DB)))


def _ensure_alert_db() -> sqlite3.Connection:
    ALERT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ALERT_DB_PATH), timeout=30, isolation_level=None)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_fired (
            trade_date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            level      TEXT NOT NULL,
            fired_at   TEXT NOT NULL,
            price      REAL,
            trigger_v  REAL,
            PRIMARY KEY (trade_date, stock_code, level)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_date ON alert_fired(trade_date)")
    return conn


def load_fired_today(today: date) -> set:
    """启动时调用：加载今天已触发的去重 key 集合 {(level, code, date_iso)}"""
    conn = _ensure_alert_db()
    try:
        rows = conn.execute(
            "SELECT level, stock_code, trade_date FROM alert_fired WHERE trade_date=?",
            (today.isoformat(),),
        ).fetchall()
        return {(r[0], r[1], r[2]) for r in rows}
    finally:
        conn.close()


def record_fire(today: date, code: str, level: str,
                price: float, trigger: float, fired_at: datetime) -> None:
    """触发时调用：写一行到 alert_fired"""
    conn = _ensure_alert_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO alert_fired "
            "(trade_date, stock_code, level, fired_at, price, trigger_v) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (today.isoformat(), code, level, fired_at.strftime("%Y-%m-%d %H:%M:%S"),
             float(price), float(trigger)),
        )
    finally:
        conn.close()


def cleanup_older_than(today: date, keep_days: int = 7) -> int:
    """删除 keep_days 天之前的记录，返回删除行数"""
    cutoff = (today - timedelta(days=keep_days)).isoformat()
    conn = _ensure_alert_db()
    try:
        cur = conn.execute("DELETE FROM alert_fired WHERE trade_date < ?", (cutoff,))
        return cur.rowcount or 0
    finally:
        conn.close()


# ====================================================================
# 阈值表
# ====================================================================
RULES = [
    # 持仓股 600330 天通股份
    {"code": "600330", "name": "天通股份", "level": "stop_loss",  "trigger": 27.00, "dir": "below", "message": "🚨 跌破 MA20 止损线！立即挂卖 400 股 @市价"},
    {"code": "600330", "name": "天通股份", "level": "half_out",   "trigger": 32.00, "dir": "above", "message": "✅ 回到 32 回本线！建议挂卖 200 股 @32.00"},
    {"code": "600330", "name": "天通股份", "level": "take_profit","trigger": 35.00, "dir": "above", "message": "🎉 突破 35！建议清仓剩余 200 股 @35.00"},
    # 002256 兆新股份
    {"code": "002256", "name": "兆新股份", "level": "stop_loss",  "trigger": 4.50, "dir": "below", "message": "🚨 跌破 4.50 止损！全部卖出 700 股"},
    {"code": "002256", "name": "兆新股份", "level": "half_out",   "trigger": 5.10, "dir": "above", "message": "📈 涨到 5.10！建议挂卖 350 股回本"},
    {"code": "002256", "name": "兆新股份", "level": "take_profit","trigger": 5.50, "dir": "above", "message": "🎉 涨至 5.50！清仓剩余股份"},
    # 002453 华软科技
    {"code": "002453", "name": "华软科技", "level": "stop_loss_tight", "trigger": 5.95, "dir": "below", "message": "⚠️ 跌破5.95！已接近-8%止损线"},
    {"code": "002453", "name": "华软科技", "level": "stop_loss",       "trigger": 5.80, "dir": "below", "message": "🚨 跌破5.80！硬止损卖出300股"},
    {"code": "002453", "name": "华软科技", "level": "half_out",        "trigger": 6.80, "dir": "above", "message": "📈 涨到 6.80！建议挂卖 150 股"},
    {"code": "002453", "name": "华软科技", "level": "take_profit",     "trigger": 7.20, "dir": "above", "message": "🎉 涨至 7.20！清仓剩余 150 股"},
    # 002342 巨力索具
    {"code": "002342", "name": "巨力索具", "level": "limitdown_open", "trigger": 15.85, "dir": "above", "message": "⚡ 跌停板撬开！立即卖100股"},
    {"code": "002342", "name": "巨力索具", "level": "rebound_exit",   "trigger": 16.50, "dir": "above", "message": "📈 反抽16.50！强烈建议挂卖"},
    {"code": "002342", "name": "巨力索具", "level": "yc_exit",        "trigger": 17.00, "dir": "above", "message": "🟢 反弹回17.00！挂卖100股"},
    {"code": "002342", "name": "巨力索具", "level": "take_profit",    "trigger": 19.50, "dir": "above", "message": "🎉 反弹接近成本！清仓100股"},
    # 603601 再升科技
    {"code": "603601", "name": "再升科技", "level": "stop_loss",       "trigger": 16.24, "dir": "below", "message": "🚨 跌破MA20！考虑止损"},
    {"code": "603601", "name": "再升科技", "level": "hard_stop",       "trigger": 15.00, "dir": "below", "message": "🚨🚨 跌破15.00！硬止损"},
    {"code": "603601", "name": "再升科技", "level": "take_profit_half","trigger": 19.50, "dir": "above", "message": "🎉 涨到19.50！止盈一半"},
    {"code": "603601", "name": "再升科技", "level": "take_profit",     "trigger": 21.00, "dir": "above", "message": "🎉🎉 涨到21.00！清仓"},
    # 观察股 002156 通富微电
    {"code": "002156", "name": "通富微电", "level": "buy_zone",   "trigger": 55.00, "dir": "below", "message": "💰 跌至 55！可分批 100 股建仓"},
    {"code": "002156", "name": "通富微电", "level": "buy_strong", "trigger": 54.00, "dir": "below", "message": "💰💰 跌至 54！加大买入"},
    # 002709 天赐材料
    {"code": "002709", "name": "天赐材料", "level": "buy_zone",   "trigger": 54.00, "dir": "below", "message": "💰 跌至 54！可买入但等 MACD 金叉"},
    {"code": "002709", "name": "天赐材料", "level": "buy_strong", "trigger": 53.00, "dir": "below", "message": "💰💰 跌至 53！加大买入"},
    # 002149 西部材料
    {"code": "002149", "name": "西部材料", "level": "buy_zone",   "trigger": 67.00, "dir": "below", "message": "💰 跌至 67！可考虑建仓"},
    {"code": "002149", "name": "西部材料", "level": "buy_strong", "trigger": 65.00, "dir": "below", "message": "💰💰 跌至 65！强买入"},
    # 605006 山东玻纤
    {"code": "605006", "name": "山东玻纤", "level": "buy_zone",    "trigger": 13.50, "dir": "below", "message": "💰 跌至13.50！可试探建仓100股"},
    {"code": "605006", "name": "山东玻纤", "level": "buy_strong",  "trigger": 12.74, "dir": "below", "message": "💰💰 跌破MA20！谨慎加仓"},
    {"code": "605006", "name": "山东玻纤", "level": "trend_break", "trigger": 11.50, "dir": "below", "message": "⚠️ 跌破11.50！趋势可能结束"},
    # 603757 大元泵业
    {"code": "603757", "name": "大元泵业", "level": "buy_zone",    "trigger": 57.50, "dir": "below", "message": "💰 跌至57.50！可试探建仓"},
    {"code": "603757", "name": "大元泵业", "level": "buy_strong",  "trigger": 55.00, "dir": "below", "message": "💰💰 优质建仓区"},
    {"code": "603757", "name": "大元泵业", "level": "trend_break", "trigger": 49.00, "dir": "below", "message": "⚠️ 跌破MA60！趋势变化"},
]


def _is_triggered(price: float, trigger: float, direction: str) -> bool:
    if price <= 0:
        return False
    return price <= trigger if direction == "below" else price >= trigger


class ThresholdAlertStrategy(CtaTemplate):
    """vnpy CTA 风格的阈值告警策略。

    一个策略实例对应"一只股票"（vnpy 的标准模式），所以引擎初始化时
    需要为持仓 + 观察池的每只股票各创建一个实例（runner 里用 add_strategy 多次添加）。

    去重策略：用 (level, code, today_iso) 作为 key 存到 self._fired，
    并镜像到 SQLite alert_fired 表 → 进程重启可恢复。
    """

    author = "quant-learn-vnpy"
    parameters: list = []
    variables: list = ["last_price", "fired_today"]

    def __init__(self, cta_engine, strategy_name: str, vt_symbol: str, setting: dict):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.last_price: float = 0.0
        # vt_symbol 形如 '600330.SSE'
        self._symbol = vt_symbol.split(".")[0]
        self._rules = [r for r in RULES if r["code"] == self._symbol]
        self._fired: set[tuple] = set()
        self.fired_today: int = 0
        self._today: date = date.today()

    # ---------- vnpy 生命周期 ----------
    def on_init(self):
        self.write_log(f"策略初始化 {self._symbol} 命中规则数={len(self._rules)}")
        # Phase 3: 启动时从 SQLite 加载今天已触发的去重集
        try:
            self._fired = load_fired_today(self._today)
            mine = {k for k in self._fired if k[1] == self._symbol}
            self.fired_today = len(mine)
            self.write_log(f"已加载 alert_fired 记录 {len(self._fired)} 条 (本股 {len(mine)} 条)")
        except Exception as e:  # noqa: BLE001
            self.write_log(f"加载 alert_fired 失败: {e}（降级为内存去重）")

    def on_start(self):
        self.write_log("策略启动")
        push_text(f"🟢 ThresholdAlert 启动 {self._symbol} 共 {len(self._rules)} 条规则")
        # 顺手清理 7 天前的记录
        try:
            n = cleanup_older_than(self._today, keep_days=7)
            if n > 0:
                self.write_log(f"清理 alert_fired 历史记录 {n} 行")
        except Exception as e:  # noqa: BLE001
            self.write_log(f"清理历史失败: {e}")

    def on_stop(self):
        self.write_log("策略停止")

    def on_tick(self, tick):
        if tick is None or tick.last_price is None:
            return
        # 跨天清空去重 + reload
        today = date.today()
        if today != self._today:
            self._today = today
            try:
                self._fired = load_fired_today(self._today)
                cleanup_older_than(self._today, keep_days=7)
            except Exception:
                self._fired = set()
            self.fired_today = 0

        price = float(tick.last_price)
        self.last_price = price
        self._evaluate(price, tick.datetime if hasattr(tick, "datetime") else datetime.now())

    def on_bar(self, bar):
        # bar 模式（回测）下也用收盘价做一次评估
        if bar is None:
            return
        self._evaluate(float(bar.close_price), bar.datetime)

    # ---------- 内部 ----------
    def _evaluate(self, price: float, ts):
        for rule in self._rules:
            if not _is_triggered(price, rule["trigger"], rule["dir"]):
                continue
            key = (rule["level"], rule["code"], self._today.isoformat())
            if key in self._fired:
                continue
            self._fired.add(key)
            self.fired_today += 1
            text = (
                f"[{rule['name']} {rule['code']}] {rule['level']} 触发 "
                f"现价={price:.2f} 阈值={rule['trigger']} 方向={rule['dir']}\n"
                f"{rule['message']}"
            )
            self.write_log(text)
            push_text(text)
            # Phase 3: 落库
            try:
                fired_at = ts if isinstance(ts, datetime) else datetime.now()
                record_fire(self._today, rule["code"], rule["level"],
                            price, rule["trigger"], fired_at)
            except Exception as e:  # noqa: BLE001
                self.write_log(f"alert_fired 写库失败: {e}")
        self.put_event()
