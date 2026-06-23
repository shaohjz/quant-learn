#!/usr/bin/env python3
"""
每日数据拉取脚本 - 带自动重试和多数据源
"""
import sys
import os
import logging
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.data_source_manager import DataSourceManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def fetch_all_stocks():
    """拉取所有股票的今日数据"""
    # 读取股票列表
    watchlist_file = Path(__file__).parent.parent / "config" / "watchlist.json"
    if not watchlist_file.exists():
        logger.error(f"股票列表文件不存在: {watchlist_file}")
        return False
    
    import json
    with open(watchlist_file, 'r', encoding='utf-8') as f:
        watchlist = json.load(f)
    
    symbols = [item['code'] for item in watchlist if 'code' in item]
    logger.info(f"开始拉取 {len(symbols)} 只股票的数据...")
    
    manager = DataSourceManager()
    today = datetime.now().strftime("%Y%m%d")
    yesterday = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")  # 拉取最近7天
    
    success_count = 0
    failed_symbols = []
    
    for symbol in symbols:
        try:
            logger.info(f"拉取 {symbol}...")
            df = manager.fetch_data(symbol, yesterday, today)
            if df is not None and len(df) > 0:
                # 保存到 CSV
                data_dir = Path(__file__).parent.parent / "data"
                csv_file = data_dir / f"{symbol}.csv"
                
                # 如果文件存在，合并数据
                if csv_file.exists():
                    old_df = pd.read_csv(csv_file)
                    merged = pd.concat([old_df, df]).drop_duplicates(subset=['date']).sort_values('date')
                else:
                    merged = df
                
                merged.to_csv(csv_file, index=False)
                logger.info(f"✓ {symbol}: 成功保存 {len(df)} 行数据（最新: {df['date'].max()}）")
                success_count += 1
            else:
                logger.warning(f"✗ {symbol}: 返回空数据")
                failed_symbols.append(symbol)
        except Exception as e:
            logger.error(f"✗ {symbol}: 失败 - {e}")
            failed_symbols.append(symbol)
    
    logger.info(f"\n{'='*60}")
    logger.info(f"拉取完成: 成功 {success_count}/{len(symbols)}")
    if failed_symbols:
        logger.warning(f"失败股票: {', '.join(failed_symbols)}")
    logger.info(f"{'='*60}")
    
    return len(failed_symbols) == 0

if __name__ == "__main__":
    import pandas as pd
    
    success = fetch_all_stocks()
    if success:
        logger.info("✓ 所有股票数据拉取成功")
    else:
        logger.error("✗ 部分股票数据拉取失败")
        sys.exit(1)
