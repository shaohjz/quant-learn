"""
sim/realtime_price.py
实时 / 最新价格获取
- 首选：新浪实时行情 hq.sinajs.cn
- 备选：baostock 最新日线
"""

import re
import requests
import baostock as bs
import pandas as pd
from datetime import datetime, timedelta


def _sina_code(code: str) -> str:
    """将纯数字代码转为新浪格式 sz000967 / sh600000"""
    if code.startswith(("6", "9")):
        return f"sh{code}"
    return f"sz{code}"


def fetch_sina_realtime(codes: list) -> dict:
    """
    新浪实时行情批量查询。
    返回 {code: {name, open, high, low, price, volume, date, time}} 或空 {}
    """
    if not codes:
        return {}

    sina_codes = [_sina_code(c) for c in codes]
    url = f"https://hq.sinajs.cn/list={','.join(sina_codes)}"
    headers = {
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = "gbk"
        text = resp.text.strip()
    except Exception as e:
        print(f"  ⚠ 新浪行情请求失败: {e}")
        return {}

    result = {}
    # 解析形如 var hq_str_sz000967="盈峰环境,6.310,...";
    pattern = re.compile(r'var hq_str_(\w+)="(.*)";')
    for line in text.split("\n"):
        m = pattern.search(line.strip())
        if not m:
            continue
        sina_sym = m.group(1)
        raw = m.group(2)
        if not raw:
            continue
        parts = raw.split(",")
        if len(parts) < 32:
            continue

        # 提取纯数字代码
        code = sina_sym[2:]
        try:
            result[code] = {
                "name": parts[0],
                "open": float(parts[1]) if parts[1] else 0,
                "high": float(parts[4]) if parts[4] else 0,
                "low": float(parts[5]) if parts[5] else 0,
                "price": float(parts[3]) if parts[3] else 0,
                "yesterday_close": float(parts[2]) if parts[2] else 0,
                "volume": float(parts[8]) if parts[8] else 0,
                "amount": float(parts[9]) if parts[9] else 0,
                "date": parts[30],
                "time": parts[31],
            }
        except (ValueError, IndexError) as e:
            print(f"  ⚠ 解析 {code} 失败: {e}")

    return result


def fetch_baostock_latest(codes: list, days_back: int = 5) -> dict:
    """
    用 baostock 获取最近几天日线，取最后一条作为最新价。
    返回与 fetch_sina_realtime 相同格式。
    """
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days_back + 10)).strftime("%Y-%m-%d")

    lg = bs.login()
    if lg.error_code != "0":
        print(f"  ⚠ baostock 登录失败: {lg.error_msg}")
        return {}

    result = {}
    for code in codes:
        prefix = "sh" if code.startswith("6") else "sz"
        bs_code = f"{prefix}.{code}"
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="3",  # 不复权，取真实价格
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())

        if rows:
            last = rows[-1]
            result[code] = {
                "name": "",
                "open": float(last[1]) if last[1] else 0,
                "high": float(last[2]) if last[2] else 0,
                "low": float(last[3]) if last[3] else 0,
                "price": float(last[4]) if last[4] else 0,
                "yesterday_close": 0,
                "volume": float(last[5]) if last[5] else 0,
                "amount": 0,
                "date": last[0],
                "time": "",
            }

    bs.logout()
    return result


def get_latest_prices(codes: list) -> dict:
    """
    获取最新价格，只走新浪实时。
    注意：不再 fallback baostock，因为 baostock 返回是昨日收盘价，
    在盘中误当实时价会造成进场重大误伤（案例：2026-05-21 12:35
    豫能 14.88 “买入”，实际盘中已在涨停 16.37）。
    返回 {code: {name, open, high, low, price, volume, ...}}
    """
    print("  📡 获取实时行情（新浪）...")
    prices = fetch_sina_realtime(codes)

    missing = [c for c in codes if c not in prices or prices[c]["price"] <= 0]
    if missing:
        # 不再从 baostock 拿（那是昨日收盘价），避免伪“实时”价
        print(f"  ⚠ 新浪缺少 {len(missing)} 只，跳过（在交易时段外/休市/服务异常，不作为实时价使用）")

    return prices


def get_latest_prices_with_fallback(codes: list) -> dict:
    """
    只供非实时使用场景（如代码名查询/调试/复盘）调用：
    新浪 + baostock 后退。调用者需明确知道 baostock 会返回昨收盘。
    """
    print("  📡 获取行情（新浪 + baostock 作为后退）...")
    prices = fetch_sina_realtime(codes)
    missing = [c for c in codes if c not in prices or prices[c]["price"] <= 0]
    if missing:
        print(f"  ⚠ 新浪缺少 {missing}，尝试 baostock 补充（返回昨日收盘价!）...")
        bs_prices = fetch_baostock_latest(missing)
        for code, data in bs_prices.items():
            if data["price"] > 0:
                data["_source"] = "baostock_yesterday"  # 明确标记是昨日价
                prices[code] = data
    return prices


if __name__ == "__main__":
    codes = ["000967", "002256"]
    prices = get_latest_prices(codes)
    for code, d in prices.items():
        print(f"  {d.get('name', code)} ({code}): 最新价 {d['price']:.2f}, "
              f"开盘 {d['open']:.2f}, 最高 {d['high']:.2f}, 最低 {d['low']:.2f}, "
              f"成交量 {d['volume']:.0f}")
