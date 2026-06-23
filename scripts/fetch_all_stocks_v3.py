#!/usr/bin/env python3
"""
每日数据拉取脚本 v3 - 针对内网隔离环境优化
==============================================
针对内网隔离环境（所有外部数据源不可达）的降级策略：
1. 优先尝试在线数据源（DataSourceManager 已有逻辑）
2. 在线全部失败时，使用本地 CSV 缓存的最新数据
3. 如果本地缓存也缺失，则发送告警并跳过
4. 无论在线是否成功，都确保 CSV 文件存在且格式正确

cron 调用方式:
  python scripts/fetch_all_stocks_v3.py
  建议调度: 每个交易日 16:30
"""

import sys
import os
import logging
from datetime import datetime, timedelta
from pathlib import Path
import json
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.data_source_manager import DataSourceManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 企业微信 Webhook（复用已有的配置）
WEBHOOK_URL = os.environ.get("WECOM_WEBHOOK_URL", "")


def send_wecom_alert(msg: str):
    """发送企业微信告警（best-effort，失败不阻塞主流程）"""
    if not WEBHOOK_URL:
        logger.warning("未配置 WECOM_WEBHOOK_URL，跳过告警")
        return
    try:
        import urllib.request
        import json as _json
        payload = _json.dumps({
            "msgtype": "text",
            "text": {"content": msg}
        }).encode("utf-8")
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req, timeout=5)
        logger.info(f"企业微信告警发送成功: {msg[:50]}...")
    except Exception as e:
        logger.warning(f"企业微信告警发送失败: {e}")


def load_watchlist() -> list:
    """加载股票列表"""
    watchlist_file = Path(__file__).parent.parent / "config" / "watchlist.json"
    if not watchlist_file.exists():
        logger.error(f"股票列表文件不存在: {watchlist_file}")
        # 尝试从 data/*.csv 推断
        data_dir = Path(__file__).parent.parent / "data"
        csv_files = list(data_dir.glob("*.csv"))
        if csv_files:
            symbols = [f.stem for f in csv_files]
            logger.info(f"从 data/ 目录推断股票列表: {len(symbols)} 只")
            return symbols
        return []
    
    with open(watchlist_file, 'r', encoding='utf-8') as f:
        watchlist = json.load(f)
    symbols = [item['code'] for item in watchlist if 'code' in item]
    logger.info(f"从配置文件加载 {len(symbols)} 只股票")
    return symbols


def fetch_all_stocks():
    """拉取所有股票的今日数据（含降级逻辑）"""
    symbols = load_watchlist()
    if not symbols:
        logger.error("没有股票需要拉取")
        return False
    
    manager = DataSourceManager()
    today = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    
    success_count = 0
    cached_count = 0
    failed_symbols = []
    all_online_failed = True  # 跟踪是否所有在线数据源都失败
    
    # 先做一轮健康检查（快速失败检测）
    logger.info("=== 数据源健康检查 ===")
    health = manager.health_check()
    available_sources = [s for s, ok in health.items() if ok]
    if available_sources:
        logger.info(f"✓ 可用数据源: {', '.join(available_sources)}")
        all_online_failed = False
    else:
        logger.warning("⚠️ 所有在线数据源均不可用，将使用本地缓存模式")
    
    logger.info(f"\n=== 开始拉取 {len(symbols)} 只股票数据 ===")
    
    for symbol in symbols:
        try:
            df = None
            data_source = "unknown"
            
            # 策略1: 尝试从在线数据源获取
            if available_sources:
                try:
                    df = manager.fetch_data(symbol, start_date, today)
                    if df is not None and len(df) > 0:
                        data_source = "online"
                        all_online_failed = False  # 至少有一个成功
                except Exception as e:
                    logger.warning(f"{symbol}: 在线获取失败 ({e})，尝试本地缓存...")
            
            # 策略2: 在线失败，使用本地缓存
            if df is None or len(df) == 0:
                df = manager._fetch_from_local_cache(symbol, start_date, today)
                if df is not None and len(df) > 0:
                    data_source = "cache"
                    cached_count += 1
                    logger.info(f"  {symbol}: 使用本地缓存 ({len(df)} 行, 最新: {df['date'].max()})")
            
            if df is None or len(df) == 0:
                logger.error(f"✗ {symbol}: 无数据（在线+缓存均无）")
                failed_symbols.append(symbol)
                continue
            
            # 保存到 CSV
            data_dir = Path(__file__).parent.parent / "data"
            data_dir.mkdir(exist_ok=True)
            csv_file = data_dir / f"{symbol}.csv"
            
            if csv_file.exists() and data_source == "cache":
                # 缓存模式：不覆盖，只记录
                logger.info(f"  {symbol}: 缓存模式，跳过写入")
                success_count += 1
            else:
                # 在线模式或文件不存在：写入
                if csv_file.exists():
                    old_df = pd.read_csv(csv_file)
                    merged = pd.concat([old_df, df]).drop_duplicates(subset=['date']).sort_values('date')
                else:
                    merged = df
                
                merged.to_csv(csv_file, index=False)
                logger.info(f"✓ {symbol}: 保存 {len(df)} 行（最新: {df['date'].max()}, 来源: {data_source}）")
                success_count += 1
                
        except Exception as e:
            logger.error(f"✗ {symbol}: 异常 - {e}")
            failed_symbols.append(symbol)
    
    # 总结
    logger.info(f"\n{'='*60}")
    logger.info(f"拉取完成: 成功 {success_count}/{len(symbols)} (含缓存 {cached_count})")
    if failed_symbols:
        logger.warning(f"失败股票: {', '.join(failed_symbols)}")
    
    # 告警
    if all_online_failed and cached_count > 0:
        msg = f"⚠️ 数据拉取告警 ({today})\n所有在线数据源不可用，已使用本地缓存兜底（{cached_count} 只）。数据可能过期，请检查网络。"
        logger.warning(msg)
        send_wecom_alert(msg)
    elif failed_symbols:
        msg = f"⚠️ 数据拉取部分失败 ({today})\n失败股票: {', '.join(failed_symbols[:5])} 等共 {len(failed_symbols)} 只"
        logger.warning(msg)
        send_wecom_alert(msg)
    
    logger.info(f"{'='*60}")
    return len(failed_symbols) == 0


if __name__ == "__main__":
    logger.info(f"=== fetch_all_stocks_v3 启动 @ {datetime.now()} ===")
    try:
        success = fetch_all_stocks()
        if success:
            logger.info("✓ 所有股票数据拉取成功（或已使用缓存兜底）")
        else:
            logger.error("✗ 部分股票数据拉取失败")
            sys.exit(1)
    except Exception as e:
        logger.error(f"✗ 未捕获异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
