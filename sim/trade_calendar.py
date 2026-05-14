"""
sim/trade_calendar.py
A股交易日历（简化版：周一-周五 + 排除节假日列表）

未来如需精确，可改用 akshare 的 tool_trade_date_hist_sina() 拉官方交易日。
"""

from datetime import date as Date, datetime


# 2026 年 A 股节假日（手动维护，每年初更新一次）
# 数据来源：上交所/深交所官方休市公告
HOLIDAYS_2026 = {
    # 元旦
    "2026-01-01", "2026-01-02",
    # 春节
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
    # 清明
    "2026-04-06",
    # 劳动节
    "2026-05-01", "2026-05-04", "2026-05-05",
    # 端午
    "2026-06-19",
    # 中秋
    "2026-09-25",
    # 国庆
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07",
}


def is_trading_day(d: Date = None) -> bool:
    """是否为交易日"""
    d = d or Date.today()
    # 周末
    if d.weekday() >= 5:
        return False
    # 节假日
    return d.strftime("%Y-%m-%d") not in HOLIDAYS_2026


if __name__ == "__main__":
    today = Date.today()
    print(f"今天 {today} ({['周一','周二','周三','周四','周五','周六','周日'][today.weekday()]})"
          f" 是否交易日：{is_trading_day(today)}")
