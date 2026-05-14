"""
sim/signal_generator.py
信号生成器 — 基于多指标投票的复合策略
直接用 pandas + ta 计算技术指标，不依赖 backtrader。

买入条件（至少满足3个）：
  1. MACD金叉（DIF上穿DEA）
  2. RSI超卖回升（RSI<30后回到30以上，或RSI从40以下上穿40）
  3. 成交量放大（当日成交量 > 过去20日均量的1.5倍）
  4. 价格站上5日均线且5日均线拐头向上
  5. KDJ金叉（K线上穿D线，且J值<80）

卖出条件（满足2个即卖）：
  1. MACD死叉
  2. RSI超买回落（>70后回落跌破70）
  3. 价格跌破10日均线
  4. KDJ死叉且J值>80
  5. 量能萎缩至20日均量的0.5倍以下
"""

import pandas as pd
import numpy as np
import baostock as bs
from datetime import datetime, timedelta


def _fetch_kline(stock_code: str, days: int = 80) -> pd.DataFrame:
    """
    用 baostock 获取最近 days 天的日K线（不复权，取真实价格）。
    """
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days + 30)).strftime("%Y-%m-%d")

    prefix = "sh" if stock_code.startswith("6") else "sz"
    bs_code = f"{prefix}.{stock_code}"

    lg = bs.login()
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,volume",
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag="3",
    )
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    bs.logout()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    df.sort_values("date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def _calc_macd(close: pd.Series, fast=12, slow=26, signal=9):
    """返回 DIF, DEA, MACD柱"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_hist = 2 * (dif - dea)
    return dif, dea, macd_hist


def _calc_rsi(close: pd.Series, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series, n=14, m1=3, m2=3):
    """返回 K, D, J"""
    low_n = low.rolling(n).min()
    high_n = high.rolling(n).max()
    rsv = (close - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    K = rsv.ewm(com=m1 - 1, adjust=False).mean()
    D = K.ewm(com=m2 - 1, adjust=False).mean()
    J = 3 * K - 2 * D
    return K, D, J


def generate_signals(stock_code: str, stock_name: str = "",
                     existing_position: dict = None) -> dict:
    """
    生成单只股票的交易信号。
    existing_position: {quantity, avg_cost, max_price_since_buy} 或 None

    返回:
    {
      code, name, signal, reasons, price, indicators,
      risk_action, risk_reason
    }
    signal: "BUY" | "SELL" | "HOLD"
    """
    df = _fetch_kline(stock_code, days=80)
    if df.empty or len(df) < 30:
        return {
            "code": stock_code,
            "name": stock_name,
            "signal": "HOLD",
            "reasons": ["数据不足"],
            "price": 0,
            "indicators": {},
        }

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # --- 计算指标 ---
    dif, dea, macd_hist = _calc_macd(close)
    rsi = _calc_rsi(close)
    K, D, J = _calc_kdj(high, low, close)
    sma5 = close.rolling(5).mean()
    sma10 = close.rolling(10).mean()
    sma20 = close.rolling(20).mean()
    vol_ma20 = volume.rolling(20).mean()

    # 取最新两天数据
    i = len(df) - 1
    if i < 1:
        return {
            "code": stock_code, "name": stock_name,
            "signal": "HOLD", "reasons": ["数据太少"], "price": 0, "indicators": {},
        }

    latest_price = close.iloc[i]
    indicators = {
        "price": round(latest_price, 4),
        "DIF": round(dif.iloc[i], 4),
        "DEA": round(dea.iloc[i], 4),
        "MACD": round(macd_hist.iloc[i], 4),
        "RSI": round(rsi.iloc[i], 2),
        "K": round(K.iloc[i], 2),
        "D": round(D.iloc[i], 2),
        "J": round(J.iloc[i], 2),
        "MA5": round(sma5.iloc[i], 4),
        "MA10": round(sma10.iloc[i], 4),
        "MA20": round(sma20.iloc[i], 4) if pd.notna(sma20.iloc[i]) else None,
        "VOL": volume.iloc[i],
        "VOL_MA20": round(vol_ma20.iloc[i], 0) if pd.notna(vol_ma20.iloc[i]) else None,
    }

    # ========== 风控检查（持仓时） ==========
    risk_action = None
    risk_reason = None
    if existing_position and existing_position.get("quantity", 0) > 0:
        avg_cost = existing_position["avg_cost"]
        pnl_pct = (latest_price - avg_cost) / avg_cost if avg_cost > 0 else 0

        # 止损: -8%
        if pnl_pct <= -0.08:
            risk_action = "SELL"
            risk_reason = f"止损（亏损 {pnl_pct*100:.1f}%）"

        # 移动止盈: 浮盈超20%后回撤5%
        max_price = existing_position.get("max_price_since_buy", avg_cost)
        max_price = max(max_price, latest_price)
        peak_pnl = (max_price - avg_cost) / avg_cost if avg_cost > 0 else 0
        if peak_pnl >= 0.20:
            pullback = (max_price - latest_price) / max_price if max_price > 0 else 0
            if pullback >= 0.05:
                risk_action = "SELL"
                risk_reason = f"移动止盈（峰值盈 {peak_pnl*100:.1f}%, 回撤 {pullback*100:.1f}%）"

    if risk_action:
        return {
            "code": stock_code,
            "name": stock_name,
            "signal": risk_action,
            "reasons": [risk_reason],
            "price": latest_price,
            "indicators": indicators,
            "risk_action": risk_action,
            "risk_reason": risk_reason,
        }

    # ========== 买入信号 ==========
    buy_signals = []

    # 1. MACD金叉
    if dif.iloc[i - 1] <= dea.iloc[i - 1] and dif.iloc[i] > dea.iloc[i]:
        buy_signals.append("MACD金叉")

    # 2. RSI超卖回升
    if rsi.iloc[i - 1] < 30 and rsi.iloc[i] >= 30:
        buy_signals.append("RSI超卖回升(<30→>30)")
    elif rsi.iloc[i - 1] < 40 and rsi.iloc[i] >= 40:
        buy_signals.append("RSI上穿40")

    # 3. 成交量放大
    if pd.notna(vol_ma20.iloc[i]) and vol_ma20.iloc[i] > 0:
        if volume.iloc[i] > vol_ma20.iloc[i] * 1.5:
            buy_signals.append(f"放量({volume.iloc[i]/vol_ma20.iloc[i]:.1f}倍)")

    # 4. 站上5日均线且MA5拐头
    if pd.notna(sma5.iloc[i]) and pd.notna(sma5.iloc[i - 1]):
        if close.iloc[i] > sma5.iloc[i] and sma5.iloc[i] > sma5.iloc[i - 1]:
            buy_signals.append("站上MA5+MA5拐头向上")

    # 5. KDJ金叉（K上穿D，J<80）
    if K.iloc[i - 1] <= D.iloc[i - 1] and K.iloc[i] > D.iloc[i] and J.iloc[i] < 80:
        buy_signals.append("KDJ金叉(J<80)")

    # ========== 卖出信号 ==========
    sell_signals = []

    # 1. MACD死叉
    if dif.iloc[i - 1] >= dea.iloc[i - 1] and dif.iloc[i] < dea.iloc[i]:
        sell_signals.append("MACD死叉")

    # 2. RSI超买回落
    if rsi.iloc[i - 1] > 70 and rsi.iloc[i] <= 70:
        sell_signals.append("RSI超买回落(>70→<70)")

    # 3. 跌破10日均线
    if pd.notna(sma10.iloc[i]):
        if close.iloc[i] < sma10.iloc[i]:
            sell_signals.append("跌破MA10")

    # 4. KDJ死叉（J>80）
    if K.iloc[i - 1] >= D.iloc[i - 1] and K.iloc[i] < D.iloc[i] and J.iloc[i] > 80:
        sell_signals.append("KDJ死叉(J>80)")

    # 5. 量能萎缩
    if pd.notna(vol_ma20.iloc[i]) and vol_ma20.iloc[i] > 0:
        if volume.iloc[i] < vol_ma20.iloc[i] * 0.5:
            sell_signals.append(f"缩量({volume.iloc[i]/vol_ma20.iloc[i]:.2f}倍)")

    # ========== 决策 ==========
    has_position = existing_position and existing_position.get("quantity", 0) > 0

    if has_position and len(sell_signals) >= 2:
        signal = "SELL"
        reasons = sell_signals
    elif not has_position and len(buy_signals) >= 3:
        signal = "BUY"
        reasons = buy_signals
    else:
        signal = "HOLD"
        reasons = []
        if buy_signals:
            reasons.append(f"买入信号({len(buy_signals)}/3): {'+'.join(buy_signals)}")
        if sell_signals:
            reasons.append(f"卖出信号({len(sell_signals)}/2): {'+'.join(sell_signals)}")
        if not reasons:
            reasons.append("无明显信号")

    return {
        "code": stock_code,
        "name": stock_name,
        "signal": signal,
        "reasons": reasons,
        "price": latest_price,
        "indicators": indicators,
        "risk_action": risk_action,
        "risk_reason": risk_reason,
    }


if __name__ == "__main__":
    from sim.stock_pool import StockPool

    pool = StockPool()
    for code, name in pool.get_all().items():
        result = generate_signals(code, name)
        print(f"\n{'='*50}")
        print(f"{name}({code}) → 信号: {result['signal']}")
        print(f"原因: {', '.join(result['reasons'])}")
        print(f"指标: {result['indicators']}")
