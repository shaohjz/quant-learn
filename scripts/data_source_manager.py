#!/usr/bin/env python3
"""
数据源管理模块 - 支持多数据源冗余和健康检查

针对 Python OpenSSL 3.0 SSL 握手失败问题，优先使用 curl(Schannel) 方案。
"""

import time
import logging
import os
import subprocess
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import pandas as pd

logger = logging.getLogger(__name__)


class CurlHttpFetcher:
    """使用 curl (Schannel/Windows 原生 SSL) 绕过 Python OpenSSL 握手问题"""

    @staticmethod
    def _curl_get(url: str, timeout: int = 10, encoding: str = "utf-8") -> str:
        """使用 curl 获取 URL 内容，返回解码后的文本"""
        result = subprocess.run(
            ["curl", "-s", "-S", "--max-time", str(timeout), "--compressed", url],
            capture_output=True, timeout=timeout + 5
        )
        if result.returncode != 0:
            raise RuntimeError(f"curl 失败 (exit={result.returncode}): {result.stderr.decode('utf-8', errors='replace')[:200]}")
        raw = result.stdout
        # 尝试多种编码
        for enc in [encoding, "utf-8", "gbk", "gb2312", "latin-1"]:
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def fetch_sina_realtime(symbols: List[str]) -> Dict[str, dict]:
        """
        新浪免费行情接口（HTTP，无 SSL 问题）
        URL: http://hq.sinajs.cn/list=s_sh000001,s_sz399001
        返回格式: var hq_str_s_sh000001="上证指数,3245.22,1.02,0.03%";
        """
        if not symbols:
            return {}
        url = "http://hq.sinajs.cn/list=" + ",".join(symbols)
        try:
            text = CurlHttpFetcher._curl_get(url, timeout=8, encoding="gbk")
            result = {}
            for line in text.strip().split("\n"):
                if "hq_str_" in line:
                    key = line.split("hq_str_")[1].split("=")[0].strip()
                    val = line.split("\"")[1].split("\"")[0] if '"' in line else ""
                    fields = val.split(",")
                    if len(fields) >= 2:
                        result[key] = {"name": fields[0], "price": fields[1] if len(fields) > 1 else ""}
            return result
        except Exception as e:
            logger.warning(f"新浪行情 HTTP 失败: {e}")
            return {}

    @staticmethod
    def fetch_eastmoney_kline(symbol: str, start_date: str, end_date: str,
                               adjust: str = "qfq") -> Optional[pd.DataFrame]:
        """
        东方财富 Choice API（通过 curl 绕过 SSL）
        secid: 0.深圳 / 1.上海  eg: 0.000001, 1.600000
        """
        # 判断市场
        market = "1" if symbol.startswith("6") else "0"
        secid = f"{market}.{symbol}"
        # 复权类型: qfq=前复权, hfq=后复权, ""=不复权
        fqt = {"qfq": "1", "hfq": "2", "": "0"}.get(adjust, "1")
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
            f"?fields1=f1,f2,f3,f4,f5,f6"
            f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            f"&klt=101&fqt={fqt}&secid={secid}"
            f"&beg={start_date}&end={end_date}&ut=fa5fd1943c7b386f172d6893dbfba10b"
        )
        try:
            text = CurlHttpFetcher._curl_get(url, timeout=15)
            data = json.loads(text)
            klines = data.get("data", {}).get("klines", [])
            if not klines:
                logger.warning(f"东方财富无数据: {symbol}")
                return None
            rows = []
            for kl in klines:
                parts = kl.split(",")
                rows.append({
                    "date": parts[0],
                    "open": float(parts[1]),
                    "high": float(parts[2]),
                    "low": float(parts[3]),
                    "close": float(parts[4]),
                    "volume": float(parts[5]),
                })
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception as e:
            logger.warning(f"东方财富 curl 失败 {symbol}: {e}")
            return None

    @staticmethod
    def fetch_sina_kline(symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        新浪财经 K 线接口（HTTP，无 SSL）
        http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData
        """
        market = "sh" if symbol.startswith("6") else "sz"
        url = (
            f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
            f"?symbol={market}{symbol}&type=day"
            f"&datalen=1023&begin={start_date}&end={end_date}"
        )
        try:
            text = CurlHttpFetcher._curl_get(url, timeout=15, encoding="gbk")
            data = json.loads(text)
            if not data:
                return None
            rows = []
            for item in data:
                rows.append({
                    "date": item["day"],
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                    "volume": float(item["volume"]),
                })
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception as e:
            logger.warning(f"新浪 K 线失败 {symbol}: {e}")
            return None


class DataSourceManager:
    """数据源管理器 - 支持多数据源冗余
    
    优先级策略：
    - 优先使用 curl(Schannel) 方案（绕过 Python OpenSSL 3.0 握手问题）
    - 备选 Python 原生方案（baostock/akshare/tushare）
    """

    # 数据源优先级：curl 方案在前，Python OpenSSL 方案在后
    SOURCE_PRIORITY = ['eastmoney_curl', 'sina_curl', 'baostock', 'tushare', 'akshare']
    
    # Zscaler SSL 拦截检测：curl HTTPS 返回 35 或 52 时说明被拦截
    ZSCALER_DETECTED = None  # None=未检测, True=被拦截, False=正常
    
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
        self.use_cache_only = self._detect_offline_mode()
    
    def _detect_offline_mode(self) -> bool:
        """
        自动检测是否处于离线模式（所有外部数据源不可达）
        
        检测逻辑：
        1. 环境变量 USE_CACHE_ONLY=true → 强制离线模式
        2. 尝试 curl 访问一个 HTTPS 站点，若失败且 curl 返回 35 (SSL错误) 
           或 52 (空响应)，则判定为 Zscaler 环境，自动进入离线模式
        3. 所有检测仅执行一次，结果缓存到类变量 ZSCALER_DETECTED
        
        Returns:
            bool: True=离线模式，False=在线模式
        """
        # 环境变量强制离线
        if os.environ.get('USE_CACHE_ONLY', '').lower() == 'true':
            logger.info("🌐 环境变量 USE_CACHE_ONLY=true，启用离线模式（仅使用本地缓存）")
            return True
        
        # 已检测过，直接返回
        if DataSourceManager.ZSCALER_DETECTED is not None:
            return DataSourceManager.ZSCALER_DETECTED
        
        # 快速探测：用 curl 访问一个 HTTPS 站点
        # Zscaler 拦截的典型 curl exit code：
        #   28 = connection timeout（握手被拦截后超时）
        #   35 = SSL/TLS handshake failed（证书不匹配）
        #   52 = Empty reply from server（HTTP 被拦截）
        #   60 = SSL certificate problem（证书验证失败）
        ZSCALER_EXIT_CODES = (28, 35, 52, 60)
        try:
            result = subprocess.run(
                ['curl', '-s', '-S', '--max-time', '5',
                 'https://push2his.eastmoney.com'],
                capture_output=True, timeout=10
            )
            if result.returncode in ZSCALER_EXIT_CODES:
                # curl 失败，判定为 Zscaler 环境
                logger.warning(
                    f"⚠️ 检测到可能的 Zscaler SSL 拦截 "
                    f"(curl exit={result.returncode})，"
                    f"自动切换到离线模式（仅使用本地缓存）"
                )
                DataSourceManager.ZSCALER_DETECTED = True
                self.source_status = {src: False for src in self.SOURCE_PRIORITY}
                return True
            else:
                DataSourceManager.ZSCALER_DETECTED = False
                return False
        except Exception as e:
            logger.warning(f"离线模式检测失败: {e}，默认使用在线模式")
            DataSourceManager.ZSCALER_DETECTED = False
            return False
        
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
        
        # 离线模式：跳过所有在线数据源，直接使用本地缓存
        if self.use_cache_only:
            logger.warning("🌐 离线模式已启用，跳过所有在线数据源，直接使用本地缓存...")
            cached_df = self._fetch_from_local_cache(symbol, start_date, end_date)
            if cached_df is not None and len(cached_df) > 0:
                logger.info(
                    f"✓ [离线模式] 从本地缓存获取 {len(cached_df)} 行数据 "
                    f"(最新: {cached_df['date'].max().strftime('%Y-%m-%d')})"
                )
                return self._normalize_columns(cached_df)
            else:
                error_msg = (
                    f"🌐 离线模式：本地缓存中无 {symbol} 的数据 "
                    f"({start_date}~{end_date})\n"
                    f"提示：请设置 USE_CACHE_ONLY=false 并修复网络后重试，"
                    f"或手动放入 CSV 文件到 data/ 目录"
                )
                logger.error(error_msg)
                raise RuntimeError(error_msg)
        
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
        
        # 所有在线数据源均失败，尝试本地 CSV 缓存兜底
        logger.warning("⚠️ 所有在线数据源均失败，尝试本地 CSV 缓存兜底...")
        cached_df = self._fetch_from_local_cache(symbol, start_date, end_date)
        if cached_df is not None and len(cached_df) > 0:
            logger.info(
                f"✓ 从本地缓存成功获取 {len(cached_df)} 行数据 "
                f"(最新: {cached_df['date'].max().strftime('%Y-%m-%d')})"
            )
            return self._normalize_columns(cached_df)
        
        # 本地缓存也无数据，报告所有失败原因
        error_msg = f"所有数据源均失败（含本地缓存）:\n" + "\n".join(errors)
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
        elif source == 'eastmoney_curl':
            return CurlHttpFetcher.fetch_eastmoney_kline(symbol, start_date, end_date, adjust)
        elif source == 'sina_curl':
            return CurlHttpFetcher.fetch_sina_kline(symbol, start_date, end_date)
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
    
    def _fetch_from_local_cache(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        从本地 data/*.csv 读取最新可用数据作为兜底
        返回 [start_date, today] 范围内本地已有数据（若有）
        注意：CSV 文件名为 6位代码（如 000301.csv）
        """
        import os
        # 支持6位代码文件名
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
        for fname in [f"{symbol}.csv", f"{symbol.lstrip('0')}.csv"]:
            csv_path = os.path.join(data_dir, fname)
            if os.path.exists(csv_path):
                break
        else:
            # 尝试6位零填充名称
            csv_path = os.path.join(data_dir, f"{symbol}.csv")
            if not os.path.exists(csv_path):
                logger.warning(f"本地缓存文件不存在: {symbol}")
                return None
        try:
            df = pd.read_csv(csv_path)
            if 'date' not in df.columns or df.empty:
                return None
            df['date'] = pd.to_datetime(df['date'])
            # 过滤日期范围
            sd = pd.to_datetime(start_date)
            ed = pd.to_datetime(end_date)
            mask = (df['date'] >= sd) & (df['date'] <= ed)
            result = df[mask].copy()
            if result.empty:
                # 返回全部本地数据（调用方自行处理）
                logger.warning(f"本地缓存无 {start_date}~{end_date} 数据，返回全部 {len(df)} 行")
                return df.sort_values('date').reset_index(drop=True)
            return result.sort_values('date').reset_index(drop=True)
        except Exception as e:
            logger.warning(f"读取本地缓存失败 {csv_path}: {e}")
            return None
    
    def health_check(self) -> Dict[str, bool]:
        """
        检查所有数据源的健康状态
        
        在离线模式（Zscaler 拦截）下，直接返回所有数据源不可用，
        避免每次健康检查都等待超时。
        
        Returns:
            Dict: {source_name: is_healthy}
        """
        results = {}
        
        # 离线模式：跳过实际检查，直接标记所有在线源为不可用
        if self.use_cache_only:
            logger.warning("🌐 离线模式：跳过在线数据源健康检查")
            for source in self.SOURCE_PRIORITY:
                results[source] = False
            return results
        
        for source in self.SOURCE_PRIORITY:
            try:
                # 使用测试股票（平安银行 000001）进行健康检查
                test_symbol = "000001"
                test_start = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
                test_end = datetime.now().strftime("%Y%m%d")
                
                df = self._fetch_from_source(source, test_symbol, test_start, test_end, "qfq")
                results[source] = df is not None and len(df) > 0
                logger.info(f"健康检查 {source}: {'OK' if results[source] else 'FAIL(empty)'}")
                
            except Exception as e:
                logger.warning(f"数据源 {source} 健康检查失败: {e}")
                results[source] = False
        
        # 在线数据源全部失败（且不是离线模式），
        # 标记所有源为不可用，避免下次再重试
        all_failed = not any(self.source_status.values())
        if all_failed and not self.use_cache_only:
            logger.warning(
                "⚠️ 所有在线数据源均失败，"
                "建议设置 USE_CACHE_ONLY=true 启用离线模式"
            )
            # 若连续失败，自动启用离线模式
            DataSourceManager.ZSCALER_DETECTED = True
            self.use_cache_only = True

        for src, ok in results.items():
            self.source_status[src] = ok
            if not ok:
                self.last_check_time[src] = time.time()
        
        return results
    
    def get_status_report(self) -> str:
        """生成数据源状态报告（含数据源健康总结）"""
        report = "## 数据源状态报告\n\n"
        
        for source in self.SOURCE_PRIORITY:
            status = "✓ 可用" if self.source_status.get(source, True) else "✗ 不可用"
            lc = self.last_check_time.get(source, 0)
            elapsed = time.time() - lc if lc > 0 else None
            if elapsed is not None and elapsed < 60:
                last_check_str = f"{int(elapsed)} 秒前"
            elif elapsed is not None and elapsed < 3600:
                last_check_str = f"{int(elapsed / 60)} 分钟前"
            elif elapsed is not None:
                last_check_str = f"{int(elapsed / 3600)} 小时前"
            else:
                last_check_str = "从未检查"
            report += f"- **{source}**: {status} (上次检查: {last_check_str})\n"
        
        # 健康总结
        available = [s for s in self.SOURCE_PRIORITY if self.source_status.get(s, True)]
        if available:
            report += f"\n**可用数据源**: {', '.join(available)}\n"
        else:
            report += "\n⚠️ **所有数据源不可用！**\n"
        
        return report
    
    def get_available_source(self) -> Optional[str]:
        """返回第一个可用的数据源名称，若无则返回 None"""
        for src in self.SOURCE_PRIORITY:
            if self.source_status.get(src, True):
                return src
        return None


if __name__ == "__main__":
    # 测试代码
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    manager = DataSourceManager()
    
    # 健康检查
    print("=== 数据源健康检查 ===")
    health = manager.health_check()
    for source, is_healthy in health.items():
        status = "✓" if is_healthy else "✗"
        print(f"{source}: {status}")
    
    # 测试数据获取
    print("\n=== 测试数据获取 ===")
    try:
        df = manager.fetch_data("000001", "20260610", "20260616")
        print(f"成功获取 {len(df)} 行数据")
        print(df.head())
    except Exception as e:
        print(f"失败: {e}")
