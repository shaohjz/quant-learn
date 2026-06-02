"""Market sentiment snapshot for daily review (REQ-017).

The daily review should not depend on any single flaky market-data endpoint.  This
module therefore treats every data source as best-effort: unavailable fields are
kept as ``None`` and rendered as ``N/A`` instead of breaking the report.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Any


@dataclass
class MarketSentiment:
    trade_date: str
    limit_up_count: int | None = None
    limit_down_count: int | None = None
    up_count: int | None = None
    down_count: int | None = None
    flat_count: int | None = None
    northbound_net_buy: float | None = None  # 亿元
    hs300_pct: float | None = None
    leading_stock: str | None = None
    leading_stock_pct: float | None = None
    source: str = "akshare"
    error: str | None = None

    @property
    def breadth_text(self) -> str:
        if self.up_count is None or self.down_count is None:
            return "N/A"
        flat = 0 if self.flat_count is None else self.flat_count
        return f"上涨 {self.up_count} / 下跌 {self.down_count} / 平盘 {flat}"

    @property
    def risk_label(self) -> str:
        lu = self.limit_up_count
        ld = self.limit_down_count
        up = self.up_count
        down = self.down_count
        if lu is None and ld is None and (up is None or down is None):
            return "数据不足"
        if ld is not None and lu is not None:
            if ld >= max(20, lu * 0.8):
                return "偏弱/注意跌停扩散"
            if lu >= max(50, ld * 3 + 1):
                return "偏强/情绪活跃"
        if up is not None and down is not None and (up + down) > 0:
            ratio = up / max(up + down, 1)
            if ratio >= 0.60:
                return "偏强"
            if ratio <= 0.40:
                return "偏弱"
        return "中性"

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["breadth_text"] = self.breadth_text
        out["risk_label"] = self.risk_label
        return out


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        # pandas uses NaN; NaN != NaN
        v = float(value)
        return None if v != v else v
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    v = _safe_float(value)
    return None if v is None else int(round(v))


def _date_compact(d: date) -> str:
    return d.strftime("%Y%m%d")


def fetch_market_sentiment(target_date: date | None = None) -> MarketSentiment:
    """Fetch a best-effort A-share market sentiment snapshot.

    Data fields:
    - limit-up / limit-down count: Eastmoney limit pool via AKShare
    - up/down/flat breadth: Eastmoney A-share spot via AKShare (only for live/current day)
    - northbound net buy and HS300 pct: Eastmoney HSGT history via AKShare

    The function is intentionally exception-safe so daily review generation can
    still finish when external data endpoints are blocked or rate-limited.
    """
    target_date = target_date or date.today()
    snap = MarketSentiment(trade_date=target_date.isoformat())
    errors: list[str] = []

    try:
        import akshare as ak  # type: ignore
    except Exception as exc:
        snap.source = "unavailable"
        snap.error = f"akshare unavailable: {exc}"
        return snap

    compact = _date_compact(target_date)

    try:
        zt = ak.stock_zt_pool_em(date=compact)
        snap.limit_up_count = int(len(zt))
    except Exception as exc:
        errors.append(f"limit_up: {type(exc).__name__}")

    try:
        dt = ak.stock_zt_pool_dtgc_em(date=compact)
        snap.limit_down_count = int(len(dt))
    except Exception as exc:
        errors.append(f"limit_down: {type(exc).__name__}")

    # Breadth is only meaningful for current spot data; use it when target_date is
    # today to avoid mixing historical review dates with current-day breadth.
    if target_date == date.today():
        try:
            spot = ak.stock_zh_a_spot_em()
            pct_col = "涨跌幅"
            if pct_col in spot.columns:
                pct = spot[pct_col].apply(_safe_float)
                snap.up_count = int((pct > 0).sum())
                snap.down_count = int((pct < 0).sum())
                snap.flat_count = int((pct == 0).sum())
        except Exception as exc:
            errors.append(f"breadth: {type(exc).__name__}")

    try:
        hsgt = ak.stock_hsgt_hist_em(symbol="北向资金")
        if not hsgt.empty and "日期" in hsgt.columns:
            # Find exact date if present; otherwise use the latest available row
            # not after target_date.  This handles holidays and delayed data.
            df = hsgt.copy()
            df["_date"] = df["日期"].astype(str)
            exact = df[df["_date"] == target_date.isoformat()]
            if exact.empty:
                exact = df[df["_date"] <= target_date.isoformat()].tail(1)
            row = exact.iloc[-1] if not exact.empty else df.iloc[-1]
            snap.northbound_net_buy = _safe_float(row.get("当日成交净买额"))
            snap.hs300_pct = _safe_float(row.get("沪深300-涨跌幅"))
            leader = row.get("领涨股")
            snap.leading_stock = None if leader is None else str(leader)
            snap.leading_stock_pct = _safe_float(row.get("领涨股-涨跌幅"))
    except Exception as exc:
        errors.append(f"northbound: {type(exc).__name__}")

    snap.error = "; ".join(errors) if errors else None
    return snap


def _fmt_num(value: Any, suffix: str = "", digits: int = 0) -> str:
    v = _safe_float(value)
    if v is None:
        return "N/A"
    return f"{v:.{digits}f}{suffix}"


def render_market_sentiment_section(sentiment: MarketSentiment | dict[str, Any], compact: bool = False) -> str:
    """Render market sentiment as Markdown for full/WeCom daily review."""
    if isinstance(sentiment, MarketSentiment):
        data = sentiment.to_dict()
    else:
        data = dict(sentiment)
        data.setdefault("breadth_text", "N/A")
        data.setdefault("risk_label", "数据不足")

    lu = "N/A" if data.get("limit_up_count") is None else str(data.get("limit_up_count"))
    ld = "N/A" if data.get("limit_down_count") is None else str(data.get("limit_down_count"))
    north = _fmt_num(data.get("northbound_net_buy"), " 亿", 2)
    hs300 = _fmt_num(data.get("hs300_pct"), "%", 2)
    leader = data.get("leading_stock") or "N/A"
    leader_pct = _fmt_num(data.get("leading_stock_pct"), "%", 2)

    if compact:
        return (
            f"🌡️ 市场情绪：{data.get('risk_label')} | "
            f"涨停 {lu} / 跌停 {ld} | 北向 {north} | HS300 {hs300}"
        )

    lines = ["## 🌡️ 大盘情绪", ""]
    lines.append(f"- 情绪判断：**{data.get('risk_label')}**")
    lines.append(f"- 涨跌停：涨停 **{lu}** 家 / 跌停 **{ld}** 家")
    lines.append(f"- 市场宽度：{data.get('breadth_text')}")
    lines.append(f"- 北向资金：{north}；沪深300：{hs300}")
    lines.append(f"- 领涨股：{leader}（{leader_pct}）")
    if data.get("error"):
        lines.append(f"- 数据提示：部分指标暂不可用（{data['error']}）")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render_market_sentiment_section(fetch_market_sentiment(datetime.now().date())))
