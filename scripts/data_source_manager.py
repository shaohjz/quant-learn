#!/usr/bin/env python3
"""
数据源管理模块 - 支持多数据源冗余和健康检查
"""

import time
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import pandas as pd

logger = logging.getLogger(__name__)

class DataSourceManager:
    """数据源管理器 - 支持多数据源冗余"""
    
    # 数据源优先级（按速度和稳定性排序）
    SOURCE_PRIORITY = ['baostock', 'tushare', 'akshare']
    
    def __init__(self, config: Optional[Dict] = None):
        """
        初始化数据源管理器
        
        Args:
            config: 配置字典，可包含 tushare_token 等
        """
        self.config = config or {}
        self.source_status = {source: True for source in self.SOURCE_PRIORITY}
        self.last_check_time = {source: 0 for source in self.SOURCE_PRIORITY}
        self.check_interval = 3600  # 1小时检查一次数据源可用性
        
    def fetch_data(self, symbol: str, start_date: str, end_date: str, 
                   adjust: str = "qfq") -> pd.DataFrame:
        """
        从多个数据源获取股票数据（按优先级尝试）
        
        Args:
            symbol: 股票代码
            start_date: 起始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            adjust: 复权类型
            
        Returns:
            DataFrame with columns: date, open, high, low, close, volume
            
        Raises:
            RuntimeError: 所有数据源均失败
        """
        errors = []
        
        for source in self.SOURCE_PRIORITY:
            # 跳过已知不可用的数据源（除非超过检查间隔）
            if not self.source_status[source]:
                if time.time() - self.last_check_time[source] < self.check_interval:
                    logger.warning(f"数据源 {source} 已知不可用，跳过")
                    continue
                else:
                    # 超过检查间隔，重新尝试
                    logger.info(f"数据源 {source} 超过检查间隔，重新尝试")
                    self.source_status[source] = True
            
            try:
                logger.info(f"尝试从 {source} 获取数据...")
                df = self._fetch_from_source(source, symbol, start_date, end_date, adjust)
                
                if df is not None and len(df) > 0:
                    logger.info(f"✓ 从 {source} 成功获取 {len(df)} 行数据")
                    self.source_status[source] = True
                    return self._normalize_columns(df)
                else:
                    logger.warning(f"数据源 {source} 返回空数据")
                    errors.append(f"{source}: 返回空数据")
                    
            except Exception as e:
                logger.error(f"数据源 {source} 失败: {e}")
                errors.append(f"{source}: {str(e)}")
                self.source_status[source] = False
                self.last_check_time[source] = time.time()
        
        # 所有数据源均失败
        error_msg = f"所有数据源均失败:\n" + "\n".join(errors)
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    def _fetch_from_source(self, source: str, symbol: str, start_date: str, 
                          end_date: str, adjust: str) -> Optional[pd.DataFrame]:
        """从指定数据源获取数据"""
        if source == 'akshare':
            return self._fetch_from_akshare(symbol, start_date, end_date, adjust)
        elif source == 'baostock':
            return self._fetch_from_baostock(symbol, start_date, end_date, adjust)
        elif source == 'tushare':
            return self._fetch_from_tushare(symbol, start_date, end_date, adjust)
        else:
            raise ValueError(f"未知数据源: {source}")
    
    def _fetch_from_akshare(self, symbol: str, start_date: str, 
                           end_date: str, adjust: str) -> pd.DataFrame:
        """从 AKShare 获取数据"""
        import akshare as ak
        
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )
        return df
    
    def _fetch_from_baostock(self, symbol: str, start_date: str,
                             end_date: str, adjust: str) -> pd.DataFrame:
        """从 BaoStock 获取数据"""
        import baostock as bs
        
        # 登录
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"BaoStock 登录失败: {lg.error_msg}")
        
        # 构造股票代码
        prefix = "sh" if symbol.startswith("6") else "sz"
        bs_code = f"{prefix}.{symbol}"
        
        # 转换日期格式
        sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
        
        # 查询数据
        adjust_flag = "2" if adjust == "qfq" else "1"  # 2=前复权, 1=后复权
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume",
            start_date=sd,
            end_date=ed,
            frequency="d",
            adjustflag=adjust_flag,
        )
        
        # 解析结果
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        
        bs.logout()
        
        if not rows:
            return None
            
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        return df
    
    def _fetch_from_tushare(self, symbol: str, start_date: str,
                            end_date: str, adjust: str) -> pd.DataFrame:
        """从 Tushare 获取数据"""
        try:
            import tushare as ts
        except ImportError:
            raise RuntimeError("Tushare 未安装，请执行: pip install tushare")
        
        # 检查 token
        token = self.config.get('tushare_token') or os.environ.get('TUSHARE_TOKEN')
        if not token:
            raise RuntimeError("Tushare token 未配置，请在 config.yaml 中配置 tushare_token")
        
        # 初始化
        ts.set_token(token)
        pro = ts.pro_api()
        
        # 转换日期格式
        sd = f"{start_date[:4]}{start_date[4:6]}{start_date[6:]}"
        ed = f"{end_date[:4]}{end_date[4:6]}{end_date[6:]}"
        
        # 获取日线数据
        df = pro.daily(ts_code=f"{symbol}.SZ" if symbol.startswith(('0', '3')) else f"{symbol}.SH",
                       start_date=sd, end_date=ed)
        
        if df is not None and len(df) > 0:
            # Tushare 返回的是倒序，需要反转
            df = df.sort_values('trade_date').reset_index(drop=True)
            
        return df
    
    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """统一列名为 date, open, high, low, close, volume"""
        target_cols = ["date", "open", "high", "low", "close", "volume"]
        
        # 如果已经是目标列名
        if all(c in df.columns for c in target_cols):
            return df[target_cols]
        
        # 处理中文列名（AKShare）
        col_map_zh = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        }
        
        # 处理 Tushare 列名
        col_map_ts = {
            "trade_date": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "vol": "volume",
        }
        
        # 尝试映射
        for col_map in [col_map_zh, col_map_ts]:
            available_cols = [c for c in col_map.keys() if c in df.columns]
            if available_cols:
                df = df[available_cols].rename(columns=col_map)
                break
        
        # 确保数据类型正确
        df["date"] = pd.to_datetime(df["date"])
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(float)
        df["volume"] = df["volume"].astype(float)
        
        # 按日期排序
        df = df.sort_values("date").reset_index(drop=True)
        
        return df[target_cols]
    
    def health_check(self) -> Dict[str, bool]:
        """
        检查所有数据源的健康状态
        
        Returns:
            Dict: {source_name: is_healthy}
        """
        results = {}
        
        for source in self.SOURCE_PRIORITY:
            try:
                # 使用测试股票（平安银行 000001）进行健康检查
                test_symbol = "000001"
                test_start = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
                test_end = datetime.now().strftime("%Y%m%d")
                
                df = self._fetch_from_source(source, test_symbol, test_start, test_end, "qfq")
                results[source] = df is not None and len(df) > 0
                
            except Exception as e:
                logger.warning(f"数据源 {source} 健康检查失败: {e}")
                results[source] = False
        
        return results
    
    def get_status_report(self) -> str:
        """生成数据源状态报告"""
        report = "## 数据源状态报告\n\n"
        
        for source in self.SOURCE_PRIORITY:
            status = "✓ 可用" if self.source_status[source] else "✗ 不可用"
            last_check = time.time() - self.last_check_time[source]
            last_check_str = f"{int(last_check / 60)} 分钟前" if last_check < 3600 else f"{int(last_check / 3600)} 小时前"
            
            report += f"- **{source}**: {status} (上次检查: {last_check_str})\n"
        
        return report


if __name__ == "__main__":
    # 测试代码
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    manager = DataSourceManager()
    
    # 健康检查
    print("=== 数据源健康检查 ===")
    health = manager.health_check()
    for source, is_healthy in health.items():
        print(f"{source}: {'✓' if is_healthy else '✗'}")
    
    # 测试数据获取
    print("\n=== 测试数据获取 ===")
    try:
        df = manager.fetch_data("000001", "20260610", "20260616")
        print(f"成功获取 {len(df)} 行数据")
        print(df.head())
    except Exception as e:
        print(f"失败: {e}")
