#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据获取工具模块 - 带 Zscaler SSL 问题处理和重试逻辑

此模块提供：
1. 带重试的 HTTP/HTTPS 请求
2. SSL 错误处理和降级策略
3. 统一的数据源接口
"""

import time
import logging
import ssl
from pathlib import Path
from typing import Optional, Callable, Any

logger = logging.getLogger(__name__)

# 重试配置
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1  # 秒
DEFAULT_TIMEOUT = 30  # 秒


class SSLContextManager:
    """管理 SSL 上下文，处理 Zscaler 拦截问题"""
    
    _original_context = None
    _patched = False
    
    @classmethod
    def patch_ssl_for_zscaler(cls):
        """
        修补 SSL 以处理 Zscaler 拦截
        
        此函数尝试多种方法使 SSL 连接在 Zscaler 环境下工作：
        1. 使用更兼容的 SSL 协议版本
        2. 禁用证书验证（仅用于测试/内网环境）
        3. 配置密码套件
        
        ⚠️ 警告：禁用证书验证会降低安全性，仅应在受信任的内网环境使用
        """
        if cls._patched:
            logger.warning("SSL 已经修补过，跳过")
            return
        
        try:
            # 方法 1: 创建自定义 SSL 上下文（推荐）
            ctx = ssl.create_default_context()
            
            # 尝试使用 TLS 1.2（Zscaler 可能不支持 TLS 1.3）
            ctx.options |= ssl.OP_NO_TLSv1_3
            ctx.options |= ssl.OP_NO_TLSv1_2  # 回退到 TLS 1.1/1.0
            
            # 禁用主机名检查（仅用于测试）
            # ctx.check_hostname = False
            # ctx.verify_mode = ssl.CERT_NONE
            
            # 设置为默认上下文
            ssl._create_default_https_context = lambda: ctx
            
            logger.info("✓ SSL 上下文已修补（方法 1: 协议降级）")
            cls._patched = True
            
        except Exception as e:
            logger.error(f"SSL 修补失败: {e}")
            
            # 方法 2: 完全禁用 SSL 验证（不推荐，仅用于测试）
            logger.warning("⚠ 使用不安全的 SSL 配置（禁用证书验证）")
            ssl._create_default_https_context = ssl._create_unverified_context
            cls._patched = True
    
    @classmethod
    def restore_ssl(cls):
        """恢复原始 SSL 配置"""
        if cls._original_context and cls._patched:
            ssl._create_default_https_context = cls._original_context
            cls._patched = False
            logger.info("✓ SSL 配置已恢复")


def retry_on_error(
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    exceptions: tuple = (Exception,),
    logger: Optional[logging.Logger] = None,
):
    """
    重试装饰器
    
    Args:
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）
        exceptions: 需要捕获的异常类型
        logger: 日志记录器
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if logger:
                        logger.warning(
                            f"尝试 {attempt}/{max_retries} 失败: {e}"
                        )
                    
                    if attempt < max_retries:
                        if logger:
                            logger.info(f"等待 {retry_delay} 秒后重试...")
                        time.sleep(retry_delay)
            
            # 所有重试都失败
            if logger:
                logger.error(f"所有 {max_retries} 次尝试都失败")
            raise last_exception
        
        return wrapper
    return decorator


class DataFetcher:
    """统一的数据获取接口，带错误处理和重试逻辑"""
    
    def __init__(self, use_ssl_patch: bool = False):
        """
        初始化数据获取器
        
        Args:
            use_ssl_patch: 是否应用 SSL 修补（处理 Zscaler 问题）
        """
        if use_ssl_patch:
            SSLContextManager.patch_ssl_for_zscaler()
    
    @retry_on_error(max_retries=3, retry_delay=2)
    def fetch_url(
        self,
        url: str,
        timeout: int = DEFAULT_TIMEOUT,
        **kwargs
    ) -> str:
        """
        获取 URL 内容
        
        Args:
            url: URL 地址
            timeout: 超时时间（秒）
            **kwargs: 传递给 urllib.request.urlopen 的参数
        
        Returns:
            响应内容（字符串）
        """
        import urllib.request
        
        req = urllib.request.Request(url)
        
        # 添加 User-Agent（某些 API 需要）
        req.add_header('User-Agent', 'Mozilla/5.0')
        
        with urllib.request.urlopen(req, timeout=timeout, **kwargs) as response:
            return response.read().decode('utf-8')
    
    @retry_on_error(max_retries=3, retry_delay=2)
    def fetch_baostock_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        **kwargs
    ) -> Optional[Any]:
        """
        从 BaoStock 获取数据（带重试）
        
        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            BaoStock 查询结果
        """
        import baostock as bs
        
        # 确保已登录
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"BaoStock 登录失败: {lg.error_msg}")
        
        try:
            # 查询日K线数据
            rs = bs.query_history_k_data_plus(
                symbol,
                "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="3"  # 后复权
            )
            
            if rs.error_code != "0":
                raise RuntimeError(f"BaoStock 查询失败: {rs.error_msg}")
            
            return rs
        
        finally:
            bs.logout()
    
    def fetch_with_fallback(
        self,
        primary_func: Callable,
        fallback_func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        使用主函数获取数据，失败时回退到备用函数
        
        Args:
            primary_func: 主数据源函数
            fallback_func: 备用数据源函数
            *args, **kwargs: 传递给函数的参数
        
        Returns:
            数据（来自主数据源或备用数据源）
        """
        try:
            logger.info("尝试主数据源...")
            return primary_func(*args, **kwargs)
        except Exception as e:
            logger.warning(f"主数据源失败: {e}")
            logger.info("使用备用数据源...")
            return fallback_func(*args, **kwargs)


def test_data_fetcher():
    """测试 DataFetcher"""
    logging.basicConfig(level=logging.INFO)
    
    print("测试 DataFetcher ...")
    
    # 测试 1: 不修补 SSL
    print("\n[测试 1] 不修补 SSL，直接请求...")
    fetcher = DataFetcher(use_ssl_patch=False)
    try:
        result = fetcher.fetch_url("https://www.baidu.com", timeout=5)
        print(f"✓ 成功（{len(result)} 字节）")
    except Exception as e:
        print(f"✗ 失败: {e}")
    
    # 测试 2: 修补 SSL
    print("\n[测试 2] 修补 SSL 后请求...")
    fetcher = DataFetcher(use_ssl_patch=True)
    try:
        result = fetcher.fetch_url("https://www.baidu.com", timeout=5)
        print(f"✓ 成功（{len(result)} 字节）")
    except Exception as e:
        print(f"✗ 失败: {e}")
    
    print("\n测试完成")


if __name__ == "__main__":
    test_data_fetcher()
