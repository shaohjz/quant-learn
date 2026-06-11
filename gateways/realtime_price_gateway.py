"""
实时行情API网关 - 获取股票收盘价
支持多个数据源：AkShare（免费）、Tushare（需token）
"""
import logging
from datetime import datetime
from typing import Optional, Dict, List
import time

logger = logging.getLogger(__name__)

class RealtimePriceGateway:
    """实时行情网关 - 获取股票收盘价"""
    
    def __init__(self, source: str = "akshare", token: str = None):
        """
        初始化行情网关
        :param source: 数据源，可选 "akshare"（免费）或 "tushare"（需token）
        :param token: Tushare token（如果使用tushare）
        """
        self.source = source
        self.token = token
        self.logger = logging.getLogger(__name__)
        
        if source == "tushare" and token:
            try:
                import tushare as ts
                self.ts = ts
                self.ts.set_token(token)
                self.pro = ts.pro_api()
                self.logger.info("Tushare API 初始化成功")
            except ImportError:
                self.logger.error("请安装 tushare: pip install tushare")
                raise
        elif source == "akshare":
            try:
                import akshare as ak
                self.ak = ak
                self.logger.info("AkShare API 初始化成功")
            except ImportError:
                self.logger.error("请安装 akshare: pip install akshare")
                raise
    
    def get_realtime_price(self, symbol: str, trade_date: str = None) -> Optional[float]:
        """
        获取股票实时收盘价
        :param symbol: 股票代码，如 "600330" 或 "000001"
        :param trade_date: 交易日期，格式 "20240101"，默认为最新
        :return: 收盘价，如果没有数据返回 None
        """
        try:
            if self.source == "akshare":
                return self._get_akshare_price(symbol, trade_date)
            elif self.source == "tushare":
                return self._get_tushare_price(symbol, trade_date)
            else:
                self.logger.error(f"不支持的行情源: {self.source}")
                return None
        except Exception as e:
            self.logger.error(f"获取股票{symbol}收盘价失败: {e}")
            return None
    
    def _get_akshare_price(self, symbol: str, trade_date: str = None) -> Optional[float]:
        """使用 AkShare 获取收盘价"""
        try:
            # 获取实时行情
            if trade_date is None:
                # 获取最新一个交易日的收盘价
                df = self.ak.stock_zh_a_spot_em()
                if df is not None and not df.empty:
                    # 根据代码查找
                    code_match = df[df['代码'] == symbol]
                    if not code_match.empty:
                        return float(code_match.iloc[0]['最新价'])
            else:
                # 获取指定日期的收盘价
                # 转换日期格式：20240101 -> 2024-01-01
                date_str = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
                df = self.ak.stock_zh_a_hist(symbol=symbol, period="daily", 
                                           start_date=date_str, end_date=date_str)
                if df is not None and not df.empty:
                    return float(df.iloc[-1]['收盘'])
            
            self.logger.warning(f"AkShare 未找到股票{symbol}的收盘价数据")
            return None
        except Exception as e:
            self.logger.error(f"AkShare 获取价格失败: {e}")
            return None
    
    def _get_tushare_price(self, symbol: str, trade_date: str = None) -> Optional[float]:
        """使用 Tushare 获取收盘价"""
        try:
            if trade_date is None:
                # 获取最新交易日
                trade_date = datetime.now().strftime("%Y%m%d")
            
            # 转换股票代码格式：600330 -> 600330.SH
            if symbol.startswith(('6', '9')):
                ts_code = f"{symbol}.SH"
            else:
                ts_code = f"{symbol}.SZ"
            
            df = self.pro.daily(ts_code=ts_code, trade_date=trade_date)
            if df is not None and not df.empty:
                return float(df.iloc[0]['close'])
            
            self.logger.warning(f"Tushare 未找到股票{symbol}在{trade_date}的收盘价")
            return None
        except Exception as e:
            self.logger.error(f"Tushare 获取价格失败: {e}")
            return None
    
    def get_batch_prices(self, symbols: List[str], trade_date: str = None) -> Dict[str, Optional[float]]:
        """
        批量获取股票收盘价
        :param symbols: 股票代码列表
        :param trade_date: 交易日期
        :return: {symbol: price} 字典
        """
        results = {}
        for symbol in symbols:
            price = self.get_realtime_price(symbol, trade_date)
            results[symbol] = price
            # 避免请求过于频繁
            if self.source == "tushare":
                time.sleep(0.1)  # Tushare 有频率限制
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
            if 'conn' in locals():
                conn.rollback()
                conn.close()


def test_realtime_price_gateway():
    """测试实时行情网关"""
    print("测试实时行情网关...")
    
    # 测试 AkShare（免费）
    try:
        gateway = RealtimePriceGateway(source="akshare")
        
        # 测试单只股票
        test_symbols = ["600330", "000001", "600519"]  # 浙江鼎力、平安银行、贵州茅台
        
        print("\n1. 测试单只股票实时价格:")
        for symbol in test_symbols:
            price = gateway.get_realtime_price(symbol)
            if price:
                print(f"  {symbol}: {price:.2f}元")
            else:
                print(f"  {symbol}: 获取失败")
        
        print("\n2. 测试批量获取:")
        batch_prices = gateway.get_batch_prices(test_symbols)
        for symbol, price in batch_prices.items():
            print(f"  {symbol}: {price:.2f}元" if price else f"  {symbol}: 无数据")
        
        print("\n3. 测试指定日期价格:")
        historical_price = gateway.get_realtime_price("600330", "20240531")
        if historical_price:
            print(f"  600330在2024-05-31的收盘价: {historical_price:.2f}元")
        
    except ImportError as e:
        print(f"AkShare 未安装，请运行: pip install akshare")
        print(f"错误: {e}")
    except Exception as e:
        print(f"测试失败: {e}")


if __name__ == "__main__":
    # 设置日志
    logging.basicConfig(level=logging.INFO, 
                       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    test_realtime_price_gateway()