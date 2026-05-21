"""
vqlearn/strategies/threshold_strategy.py — 阈值告警策略

继承 vnpy CtaTemplate（兼容回测/实盘）。

每只股票配置一组规则：
- buy_zone:    回调到位价（轻仓买入信号 → 当下买）
- buy_strong:  深度回调价（重仓买入信号 → 当下买）
- trend_break: 趋势破位价（卖出信号 → **两段确认**才卖）
- take_profit: 止盈价（半仓卖 → **两段确认**才卖）

触发逻辑（v2 - 2026-05-21 升级）：
- on_tick 检查每只股票当前价
- 买入：当下立即触发（去重靠 sqlite threshold_state）
- 卖出：两段确认（盘中 pending → 当日收盘 armed → 次日开盘 confirmed → 真卖）
- 成交量过滤：触发时若 5 日均量数据可得，要求当日累计量 ≥ 0.5×5日均量×当时时段比例

跨进程跨日持久化到 sqlite，保证 fired_today 不丢。
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Any

from vnpy_ctastrategy import CtaTemplate, StopOrder
from vnpy.trader.object import TickData, BarData, OrderData, TradeData

import os, sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.environ.setdefault('QUANT_DB_PATH', str(_ROOT / 'data' / 'sim_live_mirror.db'))

try:
    from scripts.sim_executor import execute_trade as _sim_execute_trade
except Exception:
    _sim_execute_trade = None

try:
    from vqlearn.services.threshold_state import (
        evaluate_sell_signal,
        record_sell_executed,
        should_buy_now,
        record_buy_executed,
    )
except Exception:
    evaluate_sell_signal = None
    record_sell_executed = None
    should_buy_now = None
    record_buy_executed = None


# A 股交易时段判定（确定收盘价/开盘价时点）
def _is_close_window() -> bool:
    """14:55-15:00 视为收盘价确认窗口"""
    n = datetime.now().time()
    return time(14, 55) <= n <= time(15, 5)


def _is_trading_hours() -> bool:
    """是否在交易时段：9:30-11:30 或 13:00-15:00。周末不交易。"""
    n = datetime.now()
    if n.weekday() >= 5:  # 周六/周日
        return False
    t = n.time()
    return (time(9, 30) <= t <= time(11, 30)) or (time(13, 0) <= t <= time(15, 0))


def _send_wecom_notify(text: str) -> bool:
    """推送到企微群机器人。从 config.local.yaml 读 webhook URL。失败不报错。"""
    import os, json
    import urllib.request
    from pathlib import Path
    url = os.getenv('WECOM_WEBHOOK_URL')
    if not url:
        try:
            cfg = Path(__file__).resolve().parents[2] / 'config.local.yaml'
            if cfg.exists():
                import yaml
                data = yaml.safe_load(cfg.read_text(encoding='utf-8')) or {}
                url = (data.get('notifier') or {}).get('wecom_webhook')
        except Exception:
            pass
    if not url:
        return False
    try:
        body = json.dumps({"msgtype": "markdown", "markdown": {"content": text}}).encode('utf-8')
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return b'"errcode":0' in resp.read()
    except Exception:
        return False


def _trading_minutes_elapsed() -> float:
    """返回当前已开盘多少分钟（用于估算 volume 完成度）。
    上午 9:30-11:30 = 120 分钟，下午 13:00-15:00 = 120 分钟。
    """
    n = datetime.now().time()
    if n < time(9, 30):
        return 0
    if n <= time(11, 30):
        return (n.hour - 9) * 60 + n.minute - 30
    if n < time(13, 0):
        return 120
    if n <= time(15, 0):
        return 120 + (n.hour - 13) * 60 + n.minute
    return 240  # 收盘后


class ThresholdAlertStrategy(CtaTemplate):
    """单只股票的阈值告警策略 v2"""

    author = "vqlearn"

    buy_zone = 0.0
    buy_strong = 0.0
    trend_break = 0.0
    take_profit = 0.0
    fixed_size = 100
    auto_trade = False
    volume_filter = True   # 成交量过滤开关

    parameters = ["buy_zone", "buy_strong", "trend_break", "take_profit",
                  "fixed_size", "auto_trade", "volume_filter"]
    variables = ["last_price"]

    def __init__(self, cta_engine: Any, strategy_name: str, vt_symbol: str, setting: dict) -> None:
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.last_price = 0.0
        # avg_vol_5d 由 runner 在加载策略后注入；缺失则不做量过滤
        # stock_name 由 runner 注入
        # last_volume = 缓存最近一个 tick 的当日累计量（akshare 给的是当日累计 volume）

    # ----- 持久化辅助 -----
    @property
    def code(self) -> str:
        return self.vt_symbol.split('.')[0]

    @property
    def stock_name_safe(self) -> str:
        return getattr(self, 'stock_name', self.code)

    # ----- vnpy lifecycle -----
    def on_init(self) -> None:
        self.write_log(f"策略初始化: {self.vt_symbol}")
        self.write_log(
            f"  规则: buy_zone={self.buy_zone} buy_strong={self.buy_strong} "
            f"trend_break={self.trend_break} take_profit={self.take_profit} auto={self.auto_trade}"
        )

    def on_start(self) -> None:
        self.write_log(f"策略启动: {self.vt_symbol}")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log(f"策略停止: {self.vt_symbol}")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        self.last_price = tick.last_price
        self._check_rules(tick)
        self.put_event()

    def on_bar(self, bar: BarData) -> None:
        self.last_price = bar.close_price
        fake_tick = TickData(
            gateway_name=bar.gateway_name,
            symbol=bar.symbol,
            exchange=bar.exchange,
            datetime=bar.datetime,
            last_price=bar.close_price,
            volume=bar.volume,
        )
        self._check_rules(fake_tick)

    def on_order(self, order: OrderData) -> None:
        self.write_log(f"订单更新: {order.symbol} {order.direction.value} {order.volume}@{order.price:.2f} {order.status.value}")

    def on_trade(self, trade: TradeData) -> None:
        self.write_log(f"💰 成交: {trade.symbol} {trade.direction.value} {trade.volume}@{trade.price:.2f}")
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass

    # ----- 成交量过滤 -----
    def _volume_ok(self, tick: TickData) -> tuple[bool, str]:
        """检查当前成交量是否"足够"——避免开盘极短时间触发即认定。
        返回 (ok, reason)。
        """
        if not self.volume_filter:
            return True, "volume_filter off"

        avg_vol = getattr(self, 'avg_vol_5d', None)
        if not avg_vol or avg_vol <= 0:
            return True, "no avg_vol_5d"

        cur_vol = tick.volume or 0
        if cur_vol <= 0:
            return False, "tick.volume=0"

        elapsed = _trading_minutes_elapsed()
        if elapsed < 5:
            # 开盘 5 分钟内不触发任何信号（防晨抖）
            return False, f"开盘<5min 不触发 (elapsed={elapsed:.0f}m)"

        # 当前累计量应该达到 5 日均量 × (elapsed/240) × 0.5（容忍清淡日）
        expected_min = avg_vol * (elapsed / 240) * 0.5
        if cur_vol < expected_min:
            return False, f"量不足 cur={cur_vol:.0f} < 期望 {expected_min:.0f} (5d_avg={avg_vol:.0f}, elapsed={elapsed:.0f}m)"

        return True, f"量OK cur={cur_vol:.0f} (5d_avg={avg_vol:.0f})"

    # ----- 卖出执行：通过两段确认 -----
    def _try_sell(self, rule_name: str, threshold: float, price: float, tick: TickData) -> None:
        """卖出走两段确认状态机；只有 confirmed 才真下单。"""
        if evaluate_sell_signal is None:
            self.write_log(f"⚠️ threshold_state 未加载，回退当下卖")
            self._exec_via_sim(rule_name, price, f"{self.vt_symbol} 触发 {rule_name}")
            return

        is_close = _is_close_window()
        action, reason = evaluate_sell_signal(
            self.code, self.stock_name_safe, rule_name, threshold, price,
            is_close_price=is_close,
        )

        if action == 'wait':
            self.write_log(f"⏱️ [{rule_name}] {self.vt_symbol} {price:.2f}: {reason}")
        elif action == 'reset':
            self.write_log(f"♻️ [{rule_name}] {self.vt_symbol} {price:.2f}: {reason}")
        elif action == 'execute':
            self.write_log(f"🚀 [{rule_name}] {self.vt_symbol} {price:.2f}: {reason}")
            if self.auto_trade:
                success = self._exec_via_sim(rule_name, price, reason)
                if success and record_sell_executed:
                    record_sell_executed(self.code, rule_name, price, reason)

    # ----- 买入执行：当下立即（仅靠 db 去重） -----
    def _try_buy(self, rule_name: str, threshold: float, price: float, tick: TickData) -> None:
        if should_buy_now is None:
            # 退化：缺持久化时用内存去重（兼容性）
            mem = getattr(self, '_mem_fired', {})
            today = datetime.now().strftime('%Y-%m-%d')
            if mem.get(rule_name) == today:
                return
            mem[rule_name] = today
            self._mem_fired = mem
            self.write_log(f"[{rule_name}] {self.vt_symbol} {price:.2f} ≤ {threshold:.2f}（无持久化）")
            if self.auto_trade:
                self._exec_via_sim(rule_name, price, f"{self.vt_symbol} 触发 {rule_name}")
            return

        # 量过滤
        ok, vol_reason = self._volume_ok(tick)
        if not ok:
            # 量不足时只记录、不入库（让今天的盘后还有机会重新触发）
            self.write_log(f"⚠️ [{rule_name}] {self.vt_symbol} {price:.2f} ≤ {threshold:.2f}，但 {vol_reason}")
            return

        allowed, reason = should_buy_now(self.code, rule_name)
        if not allowed:
            self.write_log(f"🔁 [{rule_name}] {self.vt_symbol} {price:.2f}: {reason}")
            return

        emoji = '🟢🟢' if rule_name == 'buy_strong' else '🟢'
        self.write_log(f"{emoji} [{rule_name}] {self.vt_symbol} {price:.2f} ≤ {threshold:.2f} ({vol_reason})")

        if self.auto_trade:
            success = self._exec_via_sim(rule_name, price, f"{self.vt_symbol} 触发 {rule_name} | {vol_reason}")
            if success and record_buy_executed:
                record_buy_executed(
                    self.code, self.stock_name_safe, rule_name, threshold, price,
                    notes=f"vol={tick.volume:.0f}"
                )
            elif not success:
                # 触发但没成交（现金不足/价格不合理/涨跌停）发通知提醒
                _send_wecom_notify(
                    f"## ⚠️ vqlearn 信号未成交\n"
                    f"**{self.stock_name_safe} ({self.code})**\n\n"
                    f"- 触发: 🟢 `{rule_name}` @¥{price:.2f}\n"
                    f"- 详情: 查看日志看为什么未成交\n"
                    f"- 时间: {datetime.now().strftime('%H:%M:%S')}"
                )

    # ----- sim_executor 真下单 -----
    def _exec_via_sim(self, level: str, price: float, msg: str) -> bool:
        """返回 True 仅当下单成功（并写入 sim_trades）。"""
        if _sim_execute_trade is None:
            self.write_log("⚠️ sim_executor 未加载，跳过下单")
            return False
        rule = {'code': self.code, 'name': self.stock_name_safe, 'level': level, 'message': msg}
        try:
            r = _sim_execute_trade(rule, price)
            if r.get('success'):
                self.write_log(f"💰 [sim_executor] {r.get('action')} → {r.get('message')}")
                # 发企微通知
                action = r.get('action', level.upper())
                msg_short = r.get('message', '')
                # 判断买卖方向
                is_buy = level in ('buy_zone', 'buy_strong') or 'BUY' in str(action).upper()
                arrow = '🔴 买入' if is_buy else '🟢 卖出'
                emoji_map = {'buy_zone': '🟢', 'buy_strong': '🟢🟢', 'trend_break': '🔴', 'take_profit': '🟡'}
                rule_emoji = emoji_map.get(level, '⚪')
                notify_text = (
                    f"## {arrow} vqlearn 自动下单\n"
                    f"**{self.stock_name_safe} ({self.code})**\n\n"
                    f"- 规则: {rule_emoji} `{level}`\n"
                    f"- 成交价: ¥{price:.2f}\n"
                    f"- 详情: {msg_short}\n"
                    f"- 时间: {datetime.now().strftime('%H:%M:%S')}"
                )
                _send_wecom_notify(notify_text)
                return True
            else:
                self.write_log(f"⚠️ [sim_executor] {r.get('action')}失败: {r.get('message')}")
                return False
        except Exception as e:
            self.write_log(f"❌ [sim_executor] 执行异常: {e}")
            return False

    # ----- 规则检查（核心） -----
    def _check_rules(self, tick: TickData) -> None:
        price = tick.last_price
        if price <= 0:
            return

        # 交易时段守卫：中午/业余/周末不产生指令
        # 例外：收盘窗口（14:55-15:05）需要推进状态机，保留
        if not _is_trading_hours() and not _is_close_window():
            return

        # ---- 先看卖出（两段确认） ----
        # 持仓股股性质由 runner 配；卖单只在持仓股有意义。但这里只判信号，
        # 落地能不能卖由 sim_executor.decide_action 决定（持仓→真卖；观察股→NO_ACTION）
        if self.trend_break > 0:
            # 触发 OR 不触发都要喂给状态机（pending → close → next_day 推进）
            if price <= self.trend_break or _is_close_window():
                self._try_sell('trend_break', self.trend_break, price, tick)

        if self.take_profit > 0:
            if price >= self.take_profit or _is_close_window():
                self._try_sell('take_profit', self.take_profit, price, tick)

        # ---- 再看买入（当下） ----
        # buy_strong 优先于 buy_zone（深的优先）
        if self.buy_strong > 0 and price <= self.buy_strong:
            self._try_buy('buy_strong', self.buy_strong, price, tick)
        elif self.buy_zone > 0 and price <= self.buy_zone:
            self._try_buy('buy_zone', self.buy_zone, price, tick)
