#!/usr/bin/env python3
"""
qlib_bootstrap.py — QLib 数据初始化引导脚本

下载 A 股历史日线数据到 QLib 格式，用于本地量化研究。
依赖：qlib >= 0.9, akshare

用法：
    python scripts/qlib_bootstrap.py --start 2020-01-01 --end 2026-06-01
    python scripts/qlib_bootstrap.py --dry-run   # 仅检查环境
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('qlib_bootstrap')


def check_qlib_installed() -> bool:
    try:
        import qlib
        logger.info(f"✅ qlib version: {qlib.__version__}")
        return True
    except ImportError:
        logger.error("❌ qlib 未安装，请运行：pip install qlib")
        return False


def check_akshare_installed() -> bool:
    try:
        import akshare as ak
        logger.info(f"✅ akshare version: {ak.__version__}")
        return True
    except ImportError:
        logger.error("❌ akshare 未安装，请运行：pip install akshare")
        return False


def get_qlib_data_path() -> Path:
    """返回 QLib 数据目录，默认 ~/.qlib/"""
    p = os.environ.get('QLIB_DATA_PATH', Path.home() / '.qlib')
    return Path(p)


def bootstrap(start: str, end: str, dry_run: bool = False):
    """
    引导 QLib 数据初始化。
    
    步骤：
    1. 检查 qlib/akshare 安装
    2. 下载 A 股日线数据（AKShare）
    3. 转换为 QLib 格式并存储
    """
    if not check_qlib_installed():
        return False
    if not check_akshare_installed():
        return False

    qlib_path = get_qlib_data_path()
    logger.info(f"QLib 数据目录：{qlib_path}")
    qlib_path.mkdir(parents=True, exist_ok=True)

    if dry_run:
        logger.info("🟡 dry-run 模式，不实际下载")
        return True

    try:
        import akshare as ak
        import pandas as pd

        start_date = start.replace('-', '')
        end_date = end.replace('-', '')

        logger.info(f"📥 下载 A 股日线数据：{start} ~ {end}")
        # 使用 AKShare 下载沪深 A 股日线
        df = ak.stock_zh_a_hist(
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",  # 前复权
        )
        logger.info(f"✅ 下载完成：{len(df)} 条")

        # 转换列名以适配 QLib 格式
        col_map = {
            '日期': 'date',
            '股票代码': 'symbol',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            '成交额': 'amount',
        }
        df = df.rename(columns=col_map)
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

        # 保存到 QLib 格式目录
        out_dir = qlib_path / 'stock_zh_a'
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f'data_{start_date}_{end_date}.csv'
        df.to_csv(out_file, index=False, encoding='utf-8-sig')
        logger.info(f"✅ 数据已保存：{out_file}")

        # 生成 QLib 配置文件
        qlib_cfg = {
            'provider': 'LocalProvider',
            'mount': {
                'stock_zh_a': str(out_dir),
            },
            'region': 'cn',
            'calendar': 'stock_zh_a',
        }
        cfg_file = qlib_path / 'qlib_config.yaml'
        import yaml
        with open(cfg_file, 'w', encoding='utf-8') as f:
            yaml.dump(qlib_cfg, f, allow_unicode=True)
        logger.info(f"✅ QLib 配置已生成：{cfg_file}")

        return True

    except Exception as e:
        logger.error(f"❌ 引导失败：{e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='QLib 数据引导')
    parser.add_argument('--start', default='2020-01-01', help='开始日期')
    parser.add_argument('--end', default=date.today().isoformat(), help='结束日期')
    parser.add_argument('--dry-run', action='store_true', help='仅检查环境')
    args = parser.parse_args()

    ok = bootstrap(args.start, args.end, args.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
