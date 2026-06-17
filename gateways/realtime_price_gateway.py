"""
实时行情API网关 - 获取股票收盘价
支持多数据源自动切换：BaoStock（主源）、AkShare（备选）、Tushare（需token）
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import time

logger = logging.getLogger(__name__)

# 数据源优先级（从高到低）
# BaoStock 更稳定，作为主源；AKShare 作为备选
# BaoStock 为主源（稳定），新浪实时行情为盘中备选，AKShare 已连续 7 天不可用
# 2026-06-16: 永久移除 AKShare 备选，改用新浪实时行情 + BaoStock
DEFAULT_SOURCES = ["baostock", "sina"]


def _baostock_code(symbol: str) -> str:
    """转换股票代码为 BaoStock 格式"""
    prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    return f"{prefix}.{symbol}"


def _get_baostock_price(symbol: str, trade_date: str = None) -> Optional[float]:
    """使用 BaoStock 获取收盘价"""
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code != "0":
            logger.warning(f"BaoStock 登录失败: {lg.error_msg}")
            return None
        try:
            bs_code = _baostock_code(symbol)
            if trade_date is None:
                # 获取最近一个交易日
                trade_date_dt = datetime.now() - timedelta(days=1)
                # 跳过周末
                while trade_date_dt.weekday() >= 5:
                    trade_date_dt -= timedelta(days=1)
                date_str = trade_date_dt.strftime("%Y-%m-%d")
            else:
                # 转换 YYYYMMDD -> YYYY-MM-DD
                date_str = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"

            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,close",
                start_date=date_str,
                end_date=date_str,
                frequency="d",
                adjustflag="2",
            )
            data_list = []
            while (rs.error_code == "0") and rs.next():
                data_list.append(rs.get_row_data())
            if data_list:
                return float(data_list[-1][1])
            return None
        finally:
            bs.logout()
    except Exception as e:
        logger.warning(f"BaoStock 获取 {symbol} 价格失败: {e}")
        return None


def _get_sina_price(symbol: str, trade_date: str = None) -> Optional[float]:
    """使用新浪实时行情获取最新价（盘中实时，非收盘价）"""
    try:
        import requests
        import re
        prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
        url = f"https://hq.sinajs.cn/list={prefix}{symbol}"
        headers = {
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0",
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = "gbk"
        text = resp.text.strip()
        m = re.search(rf'var hq_str_{prefix}{symbol}="(.*)";', text)
        if m:
            parts = m.group(1).split(",")
            if len(parts) >= 32:
                price = float(parts[3]) if parts[3] else 0
                yclose = float(parts[2]) if parts[2] else 0
                if price == 0 and yclose > 0:
                    price = yclose
                return price if price > 0 else None
        return None
    except Exception as e:
        logger.warning(f"新浪获取 {symbol} 价格失败: {e}")
        return None


def _get_tushare_price(symbol: str, token: str, trade_date: str = None) -> Optional[float]:
    """使用 Tushare 获取收盘价"""
    try:
        import tushare as ts
        ts.set_token(token)
        pro = ts.pro_api()
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y%m%d")

        # 转换股票代码格式：600330 -> 600330.SH
        if symbol.startswith(("6", "9")):
            ts_code = f"{symbol}.SH"
        else:
            ts_code = f"{symbol}.SZ"

        df = pro.daily(ts_code=ts_code, trade_date=trade_date)
        if df is not None and not df.empty:
            return float(df.iloc[0]["close"])
        return None
    except Exception as e:
        logger.warning(f"Tushare 获取 {symbol} 价格失败: {e}")
        return None


class RealtimePriceGateway:
    """
    实时行情网关 - 获取股票收盘价（多数据源自动切换）
    """

    def __init__(self, sources: List[str] = None, token: str = None):
        """
        初始化行情网关（多数据源，自动切换）
        :param sources: 数据源列表，按优先级排序，默认 ["baostock", "akshare"]
        :param token: Tushare token（如果使用tushare）
        """
        self.sources = sources or DEFAULT_SOURCES
        self.token = token
        self._source_status: Dict[str, bool] = {}  # 记录各数据源可用状态
        for s in self.sources:
            self._source_status[s] = True  # 初始假设可用
        logger.info(f"实时行情网关初始化，数据源优先级: {self.sources} (AKShare 已永久移除，改用新浪实时)")

    def get_realtime_price(self, symbol: str, trade_date: str = None) -> Optional[float]:
        """
        获取股票实时收盘价（多数据源自动切换）
        :param symbol: 股票代码，如 "600330" 或 "000001"
        :param trade_date: 交易日期，格式 "20240101"，默认为最新
        :return: 收盘价，如果没有数据返回 None
        """
        for source in self.sources:
            if not self._source_status.get(source, True):
                logger.debug(f"数据源 {source} 已被标记为不可用，跳过")
                continue
            try:
                price = self._fetch_from_source(source, symbol, trade_date)
                if price is not None:
                    if not self._source_status.get(source, True):
                        logger.info(f"数据源 {source} 恢复可用")
                        self._source_status[source] = True
                    return price
            except Exception as e:
                logger.warning(f"数据源 {source} 获取 {symbol} 失败: {e}")
                self._source_status[source] = False

        logger.error(f"所有数据源均无法获取股票 {symbol} 的收盘价")
        return None

    def _fetch_from_source(self, source: str, symbol: str,
                           trade_date: str = None) -> Optional[float]:
        """从指定数据源获取价格"""
        if source == "baostock":
            return _get_baostock_price(symbol, trade_date)
        elif source == "sina":
            return _get_sina_price(symbol, trade_date)
        elif source == "tushare":
            if not self.token:
                logger.error("Tushare 需要 token，请在初始化时传入")
                return None
            return _get_tushare_price(symbol, self.token, trade_date)
        else:
            logger.error(f"不支持的行情源: {source}")
            return None

    def get_batch_prices(self, symbols: List[str], trade_date: str = None) -> Dict[str, Optional[float]]:
        """
        批量获取股票收盘价（多数据源自动切换）
        :param symbols: 股票代码列表
        :param trade_date: 交易日期
        :return: {symbol: price} 字典
        """
        results = {}
        for symbol in symbols:
            price = self.get_realtime_price(symbol, trade_date)
            results[symbol] = price
            time.sleep(0.2)  # 避免请求过于频繁
        return results

    def update_database_with_realtime_prices(self, db_path: str = None):
        """
        用实时行情更新数据库中的收盘价
        :param db_path: 数据库路径，默认为项目data目录下的sim_live_mirror.db
        """
        if db_path is None:
            from pathlib import Path
            db_path = Path(__file__).parent.parent / "data" / "sim_live_mirror.db"

        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 获取所有有持仓的股票
            cursor.execute("""
                SELECT DISTINCT stock_code FROM sim_positions
                WHERE quantity > 0
            """)
            stocks = [row[0] for row in cursor.fetchall()]

            if not stocks:
                self.logger.info("没有持仓股票需要更新价格")
                return

            self.logger.info(f"开始更新 {len(stocks)} 只股票的实时价格...")

            # 批量获取价格
            prices = self.get_batch_prices(stocks)

            # 更新数据库
            update_count = 0
            for symbol, price in prices.items():
                if price is not None:
                    cursor.execute("""
                        UPDATE sim_positions
                        SET current_price = ?, update_time = CURRENT_TIMESTAMP
                        WHERE stock_code = ?
                    """, (price, symbol))
                    update_count += 1

            conn.commit()
            conn.close()

            self.logger.info(f"成功更新 {update_count}/{len(stocks)} 只股票的实时价格")

        except Exception as e:
            self.logger.error(f"更新数据库失败: {e}")
            if "conn" in locals():
                conn.rollback()
                conn.close()

    def get_source_status(self) -> Dict[str, bool]:
        """获取各数据源可用状态"""
        return dict(self._source_status)


def test_realtime_price_gateway():
    """测试实时行情网关（多数据源）"""
    print("测试实时行情网关（多数据源自动切换）...")

    try:
        gateway = RealtimePriceGateway(sources=["baostock", "akshare"])

        test_symbols = ["600330", "000001", "600519"]  # 天通股份、平安银行、贵州茅台

        print("\n1. 测试单只股票实时价格:")
        for symbol in test_symbols:
            price = gateway.get_realtime_price(symbol)
            status = f"{price:.2f}元" if price else "获取失败"
            print(f"  {symbol}: {status}")

        print("\n2. 测试批量获取:")
        batch_prices = gateway.get_batch_prices(test_symbols)
        for symbol, price in batch_prices.items():
            status = f"{price:.2f}元" if price else "无数据"
            print(f"  {symbol}: {status}")

        print("\n3. 数据源状态:")
        for src, ok in gateway.get_source_status().items():
            print(f"  {src}: {'可用' if ok else '不可用'}")

    except Exception as e:
        print(f"测试失败: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                       format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    test_realtime_price_gateway()
