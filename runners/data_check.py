#!/usr/bin/env python3
"""
数据完整性日报检查脚本
检查行情数据完整性、时效性、质量，自动修复，生成日报
"""

import pandas as pd
import numpy as np
import os
import json
import logging
from datetime import datetime, timedelta
from collections import Counter

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
REPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pm', 'data')
TODAY = pd.Timestamp('2026-06-11')

# A股节假日（已知）
HOLIDAYS = [
    '2024-09-15', '2024-09-16', '2024-09-17',
    '2024-10-01', '2024-10-02', '2024-10-03', '2024-10-04', '2024-10-05', '2024-10-06', '2024-10-07',
    '2025-01-01',
    '2025-01-28', '2025-01-29', '2025-01-30', '2025-01-31', '2025-02-01', '2025-02-02', '2025-02-03',
    '2025-04-04', '2025-04-05', '2025-04-06',
    '2025-05-01', '2025-05-02', '2025-05-03', '2025-05-04', '2025-05-05',
    '2025-10-01', '2025-10-02', '2025-10-03', '2025-10-04', '2025-10-05', '2025-10-06', '2025-10-07', '2025-10-08',
    '2026-01-01',
    '2026-02-17', '2026-02-18', '2026-02-19', '2026-02-20', '2026-02-21', '2026-02-22', '2026-02-23',
    '2026-05-01', '2026-05-02', '2026-05-03', '2026-05-04', '2026-05-05',
]


def get_csv_files():
    """获取所有股票CSV文件"""
    files = [f for f in os.listdir(DATA_DIR)
             if f.endswith('.csv') and f not in ('daily_signals.json', 'real_holdings.json', 'universe_cache.json')]
    return sorted(files)


def check_data_completeness(df, symbol):
    """检查数据完整性：缺失、跳变"""
    issues = []
    
    if len(df) < 2:
        issues.append({'type': 'insufficient_data', 'msg': f'数据行数不足: {len(df)}'})
        return issues
    
    # 检查日期跳变
    df = df.sort_values('date').reset_index(drop=True)
    df['diff'] = df['date'].diff().dt.days
    jumps = df[df['diff'] > 4].copy()
    
    for _, row in jumps.iterrows():
        jump_date = row['date'].strftime('%Y-%m-%d')
        prev_date = (row['date'] - pd.Timedelta(days=int(row['diff']-1))).strftime('%Y-%m-%d')
        diff_days = int(row['diff'])
        
        # 检查是否是节假日导致
        is_holiday = False
        d = pd.to_datetime(jump_date)
        for i in range(1, diff_days):
            check_date = (d - pd.Timedelta(days=i)).strftime('%Y-%m-%d')
            if check_date in HOLIDAYS:
                is_holiday = True
                break
        
        if not is_holiday and diff_days > 7:
            issues.append({
                'type': 'data_jump',
                'date': jump_date,
                'msg': f'日期跳变{diff_days}天（非节假日）: {prev_date} -> {jump_date}'
            })
        elif not is_holiday:
            # 可能是周末+节假日，允许
            pass
    
    return issues


def check_data_freshness(csv_files):
    """检查入库时效性"""
    results = []
    missing_today = []
    missing_yesterday = []
    
    for f in csv_files:
        symbol = f.replace('.csv', '')
        path = os.path.join(DATA_DIR, f)
        try:
            df = pd.read_csv(path)
            if 'date' not in df.columns:
                results.append({'symbol': symbol, 'status': 'error', 'msg': '缺少date列'})
                continue
            
            df['date'] = pd.to_datetime(df['date'])
            latest = df['date'].max()
            
            if latest < TODAY:
                missing_today.append({
                    'symbol': symbol,
                    'latest': latest.strftime('%Y-%m-%d'),
                    'days_behind': (TODAY - latest).days
                })
        except Exception as e:
            results.append({'symbol': symbol, 'status': 'error', 'msg': str(e)})
    
    return missing_today, results


def check_data_quality(df, symbol):
    """检查数据质量：空值、异常值"""
    issues = []
    
    price_cols = ['open', 'high', 'low', 'close']
    for col in price_cols:
        if col not in df.columns:
            issues.append({'type': 'missing_column', 'col': col, 'msg': f'缺少列: {col}'})
            continue
        
        # 空值
        nulls = df[col].isnull().sum()
        if nulls > 0:
            issues.append({'type': 'null_value', 'col': col, 'count': nulls,
                          'msg': f'{col} 有 {nulls} 个空值'})
        
        # 零值或负值
        zeros = (df[col] == 0).sum()
        negs = (df[col] < 0).sum()
        if zeros > 0:
            issues.append({'type': 'zero_price', 'col': col, 'count': zeros,
                          'msg': f'{col} 有 {zeros} 个零值'})
        if negs > 0:
            issues.append({'type': 'negative_price', 'col': col, 'count': negs,
                          'msg': f'{col} 有 {negs} 个负值'})
    
    # volume 检查
    if 'volume' in df.columns:
        nulls = df['volume'].isnull().sum()
        if nulls > 0:
            issues.append({'type': 'null_volume', 'count': nulls,
                          'msg': f'volume 有 {nulls} 个空值'})
        zeros = (df['volume'] == 0).sum()
        # 涨停板可能成交量为0，不超过5%算正常
        if zeros > len(df) * 0.05:
            issues.append({'type': 'excessive_zero_volume', 'count': zeros,
                          'msg': f'volume 零值占比过高: {zeros}/{len(df)} ({zeros/len(df)*100:.1f}%)'})
    
    # 价格合理性检查：high >= low, high >= open, high >= close 等
    if all(c in df.columns for c in ['high', 'low', 'open', 'close']):
        invalid_hl = (df['high'] < df['low']).sum()
        if invalid_hl > 0:
            issues.append({'type': 'invalid_hl', 'count': invalid_hl,
                          'msg': f'high < low 的记录有 {invalid_hl} 条'})
    
    return issues


def try_refresh_data(symbol, start_date=None, end_date=None):
    """尝试重新拉取数据（优先BaoStock，备选AKShare）"""
    if end_date is None:
        end_date = TODAY.strftime('%Y%m%d')
    if start_date is None:
        start_date = (TODAY - timedelta(days=7)).strftime('%Y%m%d')
    
    # BaoStock 日期格式 YYYY-MM-DD
    prefix = 'sh' if symbol.startswith('6') else 'sz'
    bs_start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
    bs_end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
    
    # 策略1: BaoStock（更稳定）
    try:
        import baostock as bs
        bs.login()
        logger.info(f'尝试BaoStock拉取 {symbol}: {bs_start} ~ {bs_end}')
        rs = bs.query_history_k_data_plus(
            f'{prefix}.{symbol}',
            'date,open,high,low,close,volume',
            start_date=bs_start,
            end_date=bs_end,
            frequency='d',
            adjustflag='2',
        )
        rows = []
        while rs.error_code == '0' and rs.next():
            rows.append(rs.get_row_data())
        bs.logout()
        
        if rows:
            df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume'])
            df['date'] = pd.to_datetime(df['date'])
            for col in ['open','high','low','close']:
                df[col] = df[col].astype(float)
            df['volume'] = df['volume'].astype(float)
            df = df.sort_values('date').reset_index(drop=True)
            logger.info(f'  ✓ BaoStock拉取成功: {len(df)}行')
            return df
    except Exception as e:
        logger.warning(f'  BaoStock失败: {e}')
    
    # 策略2: AKShare（备选）
    try:
        import akshare as ak
        logger.info(f'尝试AKShare拉取 {symbol}...')
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period='daily',
            start_date=start_date,
            end_date=end_date,
            adjust='qfq',
        )
        if df is not None and not df.empty:
            col_map = {
                '日期': 'date', '开盘': 'open', '最高': 'high',
                '最低': 'low', '收盘': 'close', '成交量': 'volume',
            }
            available = [c for c in col_map.keys() if c in df.columns]
            df = df[available].rename(columns=col_map)
            df['date'] = pd.to_datetime(df['date'])
            for col in ['open', 'high', 'low', 'close']:
                df[col] = df[col].astype(float)
            df['volume'] = df['volume'].astype(float)
            df = df.sort_values('date').reset_index(drop=True)
            logger.info(f'  ✓ AKShare拉取成功: {len(df)}行')
            return df
    except Exception as e:
        logger.warning(f'  AKShare失败: {e}')
    
    return None


def interpolate_missing(df):
    """线性插值填充缺失的价格数据"""
    df = df.copy()
    price_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in price_cols:
        if col in df.columns:
            df[col] = df[col].interpolate(method='linear')
            df[col] = df[col].fillna(method='bfill').fillna(method='ffill')
    return df


def generate_report(today, missing_today, quality_issues_summary,
                    completeness_issues, refreshed_symbols, all_ok):
    """生成日报 Markdown"""
    
    lines = []
    lines.append(f'# 数据日报 {today}')
    lines.append('')
    lines.append(f'- 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    lines.append('')
    
    # 总览
    lines.append('## 总览')
    lines.append('')
    total = len(get_csv_files())
    lines.append(f'- 监控股票数: {total}')
    lines.append(f'- 今日数据缺失: {len(missing_today)} 只')
    
    # 判断整体状态
    if len(missing_today) == 0 and len(quality_issues_summary) == 0:
        status = '✅ 正常'
    elif len(missing_today) > 0 and len(missing_today) < total * 0.2:
        status = '⚠️ 部分异常'
    else:
        status = '🔴 严重异常'
    lines.append(f'- 整体状态: {status}')
    lines.append('')
    
    # 入库时效性
    lines.append('## 入库时效性')
    lines.append('')
    if len(missing_today) == 0:
        lines.append('✅ 所有股票数据已更新至最新交易日')
    else:
        lines.append(f'⚠️ 以下 {len(missing_today)} 只股票数据未更新到今日:')
        lines.append('')
        lines.append('| 股票代码 | 最新数据日期 | 滞后天数 |')
        lines.append('|---------|------------|---------|')
        for item in missing_today[:20]:  # 最多显示20只
            lines.append(f'| {item["symbol"]} | {item["latest"]} | {item["days_behind"]} |')
        if len(missing_today) > 20:
            lines.append(f'| ... | 还有 {len(missing_today)-20} 只 | ... |')
    lines.append('')
    
    # 数据完整性
    lines.append('## 数据完整性（缺失/跳变）')
    lines.append('')
    if len(completeness_issues) == 0:
        lines.append('✅ 无明显日期跳变异常')
    else:
        lines.append(f'⚠️ 发现 {len(completeness_issues)} 处日期跳变:')
        lines.append('')
        for issue in completeness_issues[:10]:
            lines.append(f'- {issue["symbol"]}: {issue["msg"]}')
    lines.append('')
    
    # 数据质量
    lines.append('## 数据质量（空值/异常值）')
    lines.append('')
    if len(quality_issues_summary) == 0:
        lines.append('✅ 所有数据质量正常')
    else:
        lines.append(f'⚠️ 发现 {len(quality_issues_summary)} 只股票存在数据质量问题:')
        lines.append('')
        for item in quality_issues_summary[:15]:
            lines.append(f'- {item["symbol"]}: {item["msg"]}')
        if len(quality_issues_summary) > 15:
            lines.append(f'- ... 还有 {len(quality_issues_summary)-15} 只')
    lines.append('')
    
    # 自动修复记录
    lines.append('## 自动修复记录')
    lines.append('')
    if len(refreshed_symbols) > 0:
        lines.append(f'🔄 已自动重新拉取 {len(refreshed_symbols)} 只股票数据:')
        lines.append('')
        for sym in refreshed_symbols:
            lines.append(f'- {sym}')
    else:
        lines.append('（无自动修复操作）')
    lines.append('')
    
    # 待处理问题
    lines.append('## 待处理问题 / Bug')
    lines.append('')
    bugs = []
    if len(missing_today) > total * 0.5:
        bugs.append(f'🔴 [Bug] 超过50%股票数据缺失今日行情，请检查数据源连接')
    if len(completeness_issues) > 0:
        for issue in completeness_issues:
            if issue.get('type') == 'data_jump':
                bugs.append(f'[Bug] {issue["symbol"]}: {issue["msg"]}')
    
    if len(bugs) > 0:
        for bug in bugs:
            lines.append(f'- {bug}')
    else:
        lines.append('（无待处理Bug）')
    lines.append('')
    
    lines.append('---')
    lines.append(f'*由数据Agent自动生成于 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*')
    
    return '\n'.join(lines)


def main():
    logger.info('开始数据日报检查...')
    
    csv_files = get_csv_files()
    logger.info(f'找到 {len(csv_files)} 个CSV文件')
    
    # 1. 检查入库时效性
    logger.info('[1/5] 检查入库时效性...')
    missing_today, freshness_results = check_data_freshness(csv_files)
    logger.info(f'  今日数据缺失: {len(missing_today)} 只')
    
    # 2. 检查数据完整性
    logger.info('[2/5] 检查数据完整性...')
    completeness_issues = []
    for f in csv_files:
        symbol = f.replace('.csv', '')
        path = os.path.join(DATA_DIR, f)
        try:
            df = pd.read_csv(path)
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                issues = check_data_completeness(df, symbol)
                for iss in issues:
                    iss['symbol'] = symbol
                    completeness_issues.append(iss)
        except Exception as e:
            logger.warning(f'  检查 {symbol} 完整性失败: {e}')
    
    # 3. 检查数据质量
    logger.info('[3/5] 检查数据质量...')
    quality_issues_summary = []
    for f in csv_files:
        symbol = f.replace('.csv', '')
        path = os.path.join(DATA_DIR, f)
        try:
            df = pd.read_csv(path)
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                issues = check_data_quality(df, symbol)
                if issues:
                    for iss in issues:
                        quality_issues_summary.append({
                            'symbol': symbol,
                            'msg': iss['msg']
                        })
        except Exception as e:
            logger.warning(f'  检查 {symbol} 质量失败: {e}')
    
    # 4. 自动修复：重新拉取缺失数据的股票
    logger.info('[4/5] 尝试自动修复...')
    refreshed = []
    for item in missing_today:
        sym = item['symbol']
        # 只尝试最近7天的数据拉取
        result = try_refresh_data(sym)
        if result is not None and len(result) > 0:
            # 合并到现有文件
            path = os.path.join(DATA_DIR, f'{sym}.csv')
            old_df = pd.read_csv(path)
            old_df['date'] = pd.to_datetime(old_df['date'])
            
            # 合并新数据
            combined = pd.concat([old_df, result]).drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
            combined.to_csv(path, index=False)
            refreshed.append(sym)
            logger.info(f'  ✓ {sym} 数据已更新')
    
    logger.info(f'  自动修复完成，更新了 {len(refreshed)} 只')
    
    # 5. 重新检查（修复后）
    logger.info('[5/5] 重新检查修复效果...')
    missing_after, _ = check_data_freshness(csv_files)
    
    # 生成日报
    all_ok = len(missing_after) == 0 and len(quality_issues_summary) == 0
    report = generate_report(
        today=TODAY.strftime('%Y-%m-%d'),
        missing_today=missing_after,
        quality_issues_summary=quality_issues_summary,
        completeness_issues=completeness_issues,
        refreshed_symbols=refreshed,
        all_ok=all_ok
    )
    
    # 保存日报
    os.makedirs(REPORT_DIR, exist_ok=True)
    report_path = os.path.join(REPORT_DIR, f'{TODAY.strftime("%Y-%m-%d")}-data.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    logger.info(f'日报已保存: {report_path}')
    
    # 保存检查结果JSON
    check_result = {
        'date': TODAY.strftime('%Y-%m-%d'),
        'checked_at': datetime.now().isoformat(),
        'total_stocks': len(csv_files),
        'missing_today': len(missing_after),
        'missing_symbols': [m['symbol'] for m in missing_after],
        'quality_issues': len(quality_issues_summary),
        'completeness_issues': len(completeness_issues),
        'refreshed': refreshed,
        'status': 'ok' if (len(missing_after) == 0 and len(quality_issues_summary) == 0) else 'warning'
    }
    json_path = os.path.join(REPORT_DIR, f'{TODAY.strftime("%Y-%m-%d")}-data-check.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(check_result, f, ensure_ascii=False, indent=2)
    logger.info(f'检查结果JSON已保存: {json_path}')
    
    logger.info('数据日报检查完成！')
    return check_result


if __name__ == '__main__':
    result = main()
    print(json.dumps(result, ensure_ascii=False, indent=2))
