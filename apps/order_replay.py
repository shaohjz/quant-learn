"""apps/order_replay.py — 基于 vnpy OmsEngine 的订单成交回放模块

OmsEngine 在内存中维护：
    - self.orders:  dict[vt_orderid, OrderData]
    - self.trades:  dict[vt_tradeid, TradeData]

本模块提供：
    1. build_replay(oms_engine, ...) -> list[ReplayEvent]
       把指定过滤条件下的订单 + 成交按时间排序，输出结构化事件流
    2. format_replay_text(events) -> str
       把事件流渲染成人类可读的文本（用于企微推送 / 复盘报告）
    3. print_replay(...) / export_replay_markdown(...)
       便捷入口

ReplayEvent 类型（按时间排序后即为"回放"）：
    - ORDER_SUBMITTED：订单提交
    - ORDER_PART_TRADED：部分成交
    - ORDER_FULLY_TRADED：全部成交
    - ORDER_CANCELLED：撤单
    - ORDER_REJECTED：拒单
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from vnpy.trader.constant import Status, Direction, Offset
from vnpy.trader.object import OrderData, TradeData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量 / 数据结构
# ---------------------------------------------------------------------------

class ReplayEventType:
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_PART_TRADED = "ORDER_PART_TRADED"
    ORDER_FULLY_TRADED = "ORDER_FULLY_TRADED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_REJECTED = "ORDER_REJECTED"


@dataclass
class ReplayEvent:
    """
    回放事件（按 datetime 排序即构成完整订单生命周期回放）
    """
    event_type: str          # ReplayEventType 常量
    datetime: Optional[datetime]  # 事件时间
    vt_orderid: str
    symbol: str = ""
    exchange: object = None
    direction: Optional[Direction] = None
    offset: Optional[Offset] = None
    price: float = 0.0
    volume: float = 0.0       # 本次成交量（对成交事件有意义）
    traded: float = 0.0       # 截至当前累计成交量
    status: object = None      # OrderData.status（原始枚举）
    tradeid: str = ""         # 仅成交事件有值
    message: str = ""         # 附加信息


@dataclass
class OrderReplaySummary:
    """单笔订单的完整回放摘要"""
    vt_orderid: str
    symbol: str
    direction: Optional[Direction] = None
    offset: Optional[Offset] = None
    order_price: float = 0.0
    order_volume: float = 0.0
    submitted_at: Optional[datetime] = None
    fully_traded_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    events: list = field(default_factory=list)
    trades: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# 核心：构建回放事件流
# ---------------------------------------------------------------------------

def _order_time(o: OrderData) -> Optional[datetime]:
    return o.datetime


def _trade_time(t: TradeData) -> Optional[datetime]:
    return t.datetime


def build_replay(
    oms_engine,
    vt_orderid: Optional[str] = None,
    symbol: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> list[ReplayEvent]:
    """
    从 OmsEngine 提取订单 + 成交，按时间排序输出回放事件流。

    :param oms_engine: vnpy OmsEngine 实例
    :param vt_orderid: 限定某笔委托（支持精确匹配 vt_orderid，
                       或仅传 orderid 后缀匹配，如 "sim-001" 匹配 "sim.sim-001"）
    :param symbol: 限定某个合约代码前缀（如 '600330' 或 '600330.SSE'）
    :param start_time: 起始时间过滤（含）
    :param end_time: 结束时间过滤（含）
    :return: 按 datetime 升序排列的 ReplayEvent 列表
    """
    events: list[ReplayEvent] = []

    all_orders = list(oms_engine.get_all_orders())
    all_trades = list(oms_engine.get_all_trades())

    # ---- 1. 过滤订单 ----
    if vt_orderid:
        # 精确匹配
        target = oms_engine.get_order(vt_orderid)
        if target:
            orders = [target]
        else:
            # 后缀匹配：vt_orderid = "sim.sim-001"，允许传 "sim-001"
            orders = [
                o for o in all_orders
                if o.vt_orderid.endswith("." + vt_orderid) or o.orderid == vt_orderid
            ]
    else:
        orders = all_orders

    # 建立 orderid -> [TradeData] 索引
    from collections import defaultdict
    trades_by_order: dict[str, list[TradeData]] = defaultdict(list)
    for t in all_trades:
        trades_by_order[t.orderid].append(t)

    # ---- 2. 生成事件 ----
    for order in orders:
        # symbol 过滤（支持 "600330" 或 "600330.SSE" 两种格式）
        if symbol:
            if not (order.symbol.startswith(symbol) or order.vt_symbol.startswith(symbol)):
                continue

        dt = _order_time(order)
        if start_time and dt and dt < start_time:
            continue
        if end_time and dt and dt > end_time:
            continue

        # 该订单的所有成交（按时间排序）
        order_trades = sorted(
            trades_by_order.get(order.vt_orderid, []),
            key=lambda t: _trade_time(t) or datetime.min,
        )

        # 提交事件
        events.append(ReplayEvent(
            event_type=ReplayEventType.ORDER_SUBMITTED,
            datetime=dt,
            vt_orderid=order.vt_orderid,
            symbol=order.vt_symbol,
            direction=order.direction,
            offset=order.offset,
            price=order.price,
            volume=order.volume,
            traded=order.traded,
            status=order.status,
        ))

        # 成交事件
        for i, trade in enumerate(order_trades):
            t_dt = _trade_time(trade)
            if start_time and t_dt and t_dt < start_time:
                continue
            if end_time and t_dt and t_dt > end_time:
                continue

            # 判断是完全成交还是部分成交
            # 规则：最后一笔成交 且 订单状态为 ALLTRADED → 完全成交
            is_last = (i == len(order_trades) - 1)
            updated = oms_engine.get_order(order.vt_orderid)
            is_fully = is_last and updated and updated.status == Status.ALLTRADED

            events.append(ReplayEvent(
                event_type=(
                    ReplayEventType.ORDER_FULLY_TRADED
                    if is_fully
                    else ReplayEventType.ORDER_PART_TRADED
                ),
                datetime=t_dt,
                vt_orderid=trade.orderid,
                tradeid=trade.tradeid,
                symbol=trade.vt_symbol,
                direction=trade.direction,
                offset=trade.offset,
                price=trade.price,
                volume=trade.volume,
                traded=(updated.traded if updated else 0),
                status=updated.status if updated else None,
            ))

        # 终态事件（无成交时追加；有成交时已通过成交事件体现）
        has_trades = bool(order_trades)
        final = oms_engine.get_order(order.vt_orderid)
        if final and not has_trades:
            if final.status == Status.CANCELLED:
                events.append(ReplayEvent(
                    event_type=ReplayEventType.ORDER_CANCELLED,
                    datetime=None,
                    vt_orderid=final.vt_orderid,
                    symbol=final.vt_symbol,
                    direction=final.direction,
                    offset=final.offset,
                    price=final.price,
                    volume=final.volume,
                    traded=final.traded,
                    status=final.status,
                    message="已撤单",
                ))
            elif final.status == Status.REJECTED:
                events.append(ReplayEvent(
                    event_type=ReplayEventType.ORDER_REJECTED,
                    datetime=None,
                    vt_orderid=final.vt_orderid,
                    symbol=final.vt_symbol,
                    direction=final.direction,
                    offset=final.offset,
                    price=final.price,
                    volume=final.volume,
                    traded=final.traded,
                    status=final.status,
                    message="订单被拒",
                ))

    # ---- 3. 按时间排序（None 排最后）----
    events.sort(key=lambda e: (e.datetime or datetime.max, e.vt_orderid))
    return events


def build_order_summaries(oms_engine) -> list[OrderReplaySummary]:
    """
    为 OmsEngine 中的每笔订单生成完整回放摘要。
    """
    from collections import defaultdict

    orders = list(oms_engine.get_all_orders())
    trades = list(oms_engine.get_all_trades())
    trades_by_order: dict[str, list] = defaultdict(list)
    for t in trades:
        trades_by_order[t.orderid].append(t)

    summaries = []
    for order in orders:
        order_trades = sorted(
            trades_by_order.get(order.vt_orderid, []),
            key=lambda t: t.datetime or datetime.min,
        )
        events = []
        status = order.status

        ev_submit = ReplayEvent(
            event_type=ReplayEventType.ORDER_SUBMITTED,
            datetime=order.datetime,
            vt_orderid=order.vt_orderid,
            symbol=order.vt_symbol,
            direction=order.direction,
            offset=order.offset,
            price=order.price,
            volume=order.volume,
            traded=order.traded,
            status=status,
        )
        events.append(ev_submit)

        for i, trade in enumerate(order_trades):
            is_last = (i == len(order_trades) - 1)
            is_fully = is_last and status == Status.ALLTRADED
            events.append(ReplayEvent(
                event_type=(
                    ReplayEventType.ORDER_FULLY_TRADED
                    if is_fully
                    else ReplayEventType.ORDER_PART_TRADED
                ),
                datetime=trade.datetime,
                vt_orderid=trade.orderid,
                tradeid=trade.tradeid,
                symbol=trade.vt_symbol,
                direction=trade.direction,
                offset=trade.offset,
                price=trade.price,
                volume=trade.volume,
                traded=order.traded,
                status=status,
            ))

        summary = OrderReplaySummary(
            vt_orderid=order.vt_orderid,
            symbol=order.vt_symbol,
            direction=order.direction,
            offset=order.offset,
            order_price=order.price,
            order_volume=order.volume,
            submitted_at=order.datetime,
            fully_traded_at=(
                order_trades[-1].datetime
                if order_trades and status == Status.ALLTRADED
                else None
            ),
            cancelled_at=(
                order.datetime if status == Status.CANCELLED else None
            ),
            rejected_at=(
                order.datetime if status == Status.REJECTED else None
            ),
            events=events,
            trades=order_trades,
        )
        summaries.append(summary)

    return summaries


# ---------------------------------------------------------------------------
# 格式化输出
# ---------------------------------------------------------------------------

_DIRECTION_CN = {
    Direction.LONG: "买入",
    Direction.SHORT: "卖出",
}
_OFFSET_CN = {
    Offset.OPEN: "开仓",
    Offset.CLOSE: "平仓",
    Offset.CLOSETODAY: "平今",
    Offset.CLOSEYESTERDAY: "平昨",
}
_STATUS_CN = {
    Status.SUBMITTING: "提交中",
    Status.NOTTRADED: "未成交",
    Status.PARTTRADED: "部分成交",
    Status.ALLTRADED: "全部成交",
    Status.CANCELLED: "已撤单",
    Status.REJECTED: "已拒单",
}


def _dir_cn(d: Optional[Direction]) -> str:
    if not d:
        return "?"
    return _DIRECTION_CN.get(d, str(d))


def _offset_cn(o: Optional[Offset]) -> str:
    if not o:
        return ""
    return _OFFSET_CN.get(o, str(o))


def _status_cn(s) -> str:
    if not s:
        return "?"
    return _STATUS_CN.get(s, str(s))


def format_replay_text(
    events: list[ReplayEvent],
    include_summary: bool = True,
) -> str:
    """将回放事件流渲染为人类可读文本（适合企微推送 / 日志）。"""
    if not events:
        return "（无订单记录）"

    lines = ["📋 订单成交回放", "=" * 36]

    from collections import defaultdict
    by_order: dict[str, list[ReplayEvent]] = defaultdict(list)
    for e in events:
        by_order[e.vt_orderid].append(e)

    for vt_id, evts in by_order.items():
        first = evts[0]
        dir_cn = _dir_cn(first.direction)
        off_cn = _offset_cn(first.offset)
        lines.append(f"\n📌 {first.symbol}  {dir_cn}{off_cn}  ({vt_id})")
        lines.append(f"   委托价 {first.price:.2f}  委托量 {int(first.volume)}")

        for e in evts:
            t_str = e.datetime.strftime("%H:%M:%S") if e.datetime else "??:??:??"
            if e.event_type == ReplayEventType.ORDER_SUBMITTED:
                lines.append(f"   {t_str}  🔵 订单提交  status={_status_cn(e.status)}")
            elif e.event_type == ReplayEventType.ORDER_PART_TRADED:
                lines.append(
                    f"   {t_str}  🟡 部分成交  "
                    f"成交价={e.price:.2f}  成交量={int(e.volume)}  "
                    f"累计={int(e.traded)}"
                )
            elif e.event_type == ReplayEventType.ORDER_FULLY_TRADED:
                lines.append(
                    f"   {t_str}  🟢 全部成交  "
                    f"成交价={e.price:.2f}  成交量={int(e.volume)}  "
                    f"累计={int(e.traded)}"
                )
            elif e.event_type == ReplayEventType.ORDER_CANCELLED:
                lines.append(f"   {t_str}  🔴 已撤单  {e.message}")
            elif e.event_type == ReplayEventType.ORDER_REJECTED:
                lines.append(f"   {t_str}  ❌ 拒单: {e.message}")

        # 小计
        if include_summary and evts:
            last = evts[-1]
            if last.event_type == ReplayEventType.ORDER_FULLY_TRADED:
                lines.append(f"   ✅ 完结: 全部成交")
            elif last.event_type == ReplayEventType.ORDER_CANCELLED:
                lines.append(f"   ⚠️ 完结: 已撤单（成交 {int(last.traded)}/{int(first.volume)}）")
            elif last.event_type == ReplayEventType.ORDER_REJECTED:
                lines.append(f"   ❌ 完结: 已拒单")

    return "\n".join(lines)


def format_order_summaries_text(summaries: list[OrderReplaySummary]) -> str:
    """将 OrderReplaySummary 列表渲染为文本。"""
    if not summaries:
        return "（无订单记录）"

    lines = ["📋 订单回放摘要", "=" * 36]
    for s in summaries:
        dir_cn = _dir_cn(s.direction)
        off_cn = _offset_cn(s.offset)
        lines.append(f"\n📌 {s.symbol}  {dir_cn}{off_cn}  ({s.vt_orderid})")
        lines.append(f"   委托价 {s.order_price:.2f}  委托量 {int(s.order_volume)}")
        if s.submitted_at:
            lines.append(f"   提交时间: {s.submitted_at.strftime('%H:%M:%S')}")
        if s.fully_traded_at:
            lines.append(f"   ✅ 全部成交 @ {s.fully_traded_at.strftime('%H:%M:%S')}")
        elif s.cancelled_at:
            lines.append(f"   🔴 已撤单 @ {s.cancelled_at.strftime('%H:%M:%S')}")
        elif s.rejected_at:
            lines.append(f"   ❌ 已拒单")
        else:
            status_cn = _status_cn(s.events[-1].status) if s.events else "未知"
            lines.append(f"   状态: {status_cn}")

        if s.trades:
            lines.append(f"   成交笔数: {len(s.trades)}")
            for t in s.trades:
                t_str = t.datetime.strftime("%H:%M:%S") if t.datetime else "??:??:??"
                lines.append(
                    f"      {t_str}  成交价={t.price:.2f} 量={int(t.volume)}  "
                    f"tradeid={t.tradeid}"
                )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------

def print_replay(oms_engine, **kwargs):
    """直接打印回放文本到 stdout（调试用）"""
    events = build_replay(oms_engine, **kwargs)
    text = format_replay_text(events)
    print(text)
    return text


def export_replay_markdown(oms_engine, filepath: str, **kwargs) -> str:
    """将回放导出为 Markdown 文件（适合写入复盘报告）。"""
    events = build_replay(oms_engine, **kwargs)
    summaries = build_order_summaries(oms_engine)

    lines = ["## 订单成交回放\n"]
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append("```\n")
    lines.append(format_replay_text(events))
    lines.append("\n```\n")

    if summaries:
        lines.append("\n## 订单摘要\n")
        lines.append("| 订单ID | 合约 | 方向 | 状态 | 委托价 | 委托量 | 累计成交 | 提交时间 |")
        lines.append("|--------|------|------|------|--------|--------|----------|----------|")
        for s in summaries:
            dir_cn = _dir_cn(s.direction)
            status_cn = _status_cn(s.events[-1].status) if s.events else "?"
            submit_str = s.submitted_at.strftime("%H:%M:%S") if s.submitted_at else "-"
            lines.append(
                f"| {s.vt_orderid} | {s.symbol} | {dir_cn} | {status_cn} "
                f"| {s.order_price:.2f} | {int(s.order_volume)} "
                f"| {int(s.events[-1].traded if s.events else 0)} | {submit_str} |"
            )

    md = "\n".join(lines)
    Path(filepath).write_text(md, encoding="utf-8")
    logger.info("回放已导出到 %s (%d chars)", filepath, len(md))
    return md


def get_replay_for_report(oms_engine) -> str:
    """供 daily_review_vnpy 等脚本调用的便捷函数。返回回放 Markdown 片段。"""
    events = build_replay(oms_engine)
    if not events:
        return ""
    return format_replay_text(events)
