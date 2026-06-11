"""
scripts/market_scanner.py - 全市场扫描器(每日盘后跑)

策略:从全 A 股里挑出有"上涨势头 + 流动性 OK"的票,自动入观察池。

筛选阶梯(层层过滤):
  1. 实时快照(5500+ 只)→ 过滤掉:
     - 名称含 ST / *ST / 退市 / N(次新当日上市)
     - 北交所(bj 开头,非主流)
     - 当日成交额 < 5000 万(流动性陷阱)
     - 当日涨幅 > 9.5%(接近涨停,追高风险)
     - 当日跌幅 < -9.5%(跌停板,可能 ST 风险)
     - 价格 < 2 元(避开仙股)

  2. 取 top 200(按成交额排序,代表市场关注度高)

  3. 对每只拉日 K 线(90 日),计算趋势分:
     - MA 多头排列 (MA5>MA10>MA20):+30
     - 当日量 > 20 日均量 1.5×:+20
     - 突破 20 日新高:+25
     - RSI 在 50-70(强势但不超买):+15
     - 趋势回踩 MA10 不破:+10

  4. 总分 ≥ 60 入候选 → top 20 自动入观察池

  5. 写入 config.yaml,标记 source='auto_scanner', strategy='trend',
     buy_zone = 当前价 × 0.97(回调 3% 触发买入)
     trend_break = MA20 × 0.95(破 MA20-5% 止损)

输出:
  - output/scanner/YYYY-MM-DD.md(候选清单 + 评分明细)
  - output/scanner/YYYY-MM-DD.json(结构化)
  - 自动改写 config.yaml watchlist(保留人工添加的,只增删 auto_scanner 的)
  - 推送企微汇总

运行:python scripts/market_scanner.py
环境变量:
  PUSH=1 → 推送企微
  DRY_RUN=1 → 只生成报告不改 config
  TOP_N=20 → 入池数量
"""
from __future__ import annotations

import os
import sys
import time
import json
import logging
import requests
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.config import load_config

logger = logging.getLogger('market-scanner')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

CONFIG_PATH = ROOT / 'config.yaml'
OUT_DIR = ROOT / 'output' / 'scanner'
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------- 配置参数(可调)----------
MIN_TURNOVER_AMT = 50_000_000   # 最低成交额 5000 万
MIN_PRICE = 2.0                 # 最低价 2 元
MAX_DAY_CHANGE = 9.5            # 涨跌幅绝对值上限(避开涨停跌停)
TOP_N_FOR_KLINE = 200           # 拉 K 线扫描的范围(避免拉 5000 次太慢)
SCORE_THRESHOLD = 60            # 入池最低评分
TOP_N_TO_POOL = int(os.environ.get('TOP_N', '20'))  # 入池数量
EXCLUDE_NAME_KEYWORDS = ['ST', '*ST', '退市', '退']  # 不排 N,改用下面的 startswith
EXCLUDE_NAME_PREFIX = ['N']  # 首字母 N 表示当日上市次新
EXCLUDE_CODE_PREFIX = ['bj', '8', '4', '92']  # 北交所
KLINE_DAYS = 90


# =================== 步骤 1: 拉全市场快照 ===================
def fetch_market_snapshot():
    """依次尝试 东财全市场 → 东财热度榜 → 新浪,多源容错"""
    import akshare as ak
    last_err = None

    # 试东财全市场(2 次 - 快失败)
    for attempt in range(2):
        try:
            t0 = time.time()
            df = ak.stock_zh_a_spot_em()
            logger.info(f'✓ 东财全市场 {len(df)} 只 / {time.time()-t0:.1f}s')
            df = df.copy()
            def _norm(c):
                c = str(c)
                if c.startswith(('60', '68', '11', '5')): return 'sh' + c
                if c.startswith(('00', '30', '15', '16')): return 'sz' + c
                if c.startswith(('43', '83', '87', '88', '92')): return 'bj' + c
                return c
            df['代码'] = df['代码'].apply(_norm)
            return df
        except Exception as e:
            last_err = e
            logger.warning(f'东财全市第 {attempt+1} 次失败: {type(e).__name__}: {str(e)[:60]}')
            time.sleep(3)

    # 回退东财热度榜(100 只 - 快且稳)
    logger.warning('回退东财热度榜...')
    try:
        t0 = time.time()
        rank = ak.stock_hot_rank_em()
        logger.info(f'✓ 热度榜 {len(rank)} 只 / {time.time()-t0:.1f}s')
        # 需要补充成交额、名称 - 热度榜只有价、涨跌
        # 重命名列适配下游
        df = rank.rename(columns={
            '代码': '代码',
            '股票名称': '名称',
            '最新价': '最新价',
            '涨跌幅': '涨跌幅',
        }).copy()
        # 代码在热度榜里是 SH600000 格式 → 转小写补全
        df['代码'] = df['代码'].astype(str).str.lower()
        # 涨跌幅为 0(盘后什么都是 0)- 仅作为种子起初始过滤
        df['成交额'] = MIN_TURNOVER_AMT * 2  # 伪赋值让流动性过滤跳过
        return df
    except Exception as e:
        last_err = e
        logger.warning(f'热度榜失败: {type(e).__name__}: {str(e)[:60]}')

    # 最后回退新浪
    logger.warning('回退新浪接口...')
    for attempt in range(2):
        try:
            t0 = time.time()
            df = ak.stock_zh_a_spot()
            logger.info(f'✓ 新浪 {len(df)} 只 / {time.time()-t0:.1f}s')
            return df
        except Exception as e:
            last_err = e
            time.sleep(5)

    raise RuntimeError(f'无法获取全市场快照: {last_err}')


# =================== 步骤 2: 第一层过滤 ===================
def basic_filter(df):
    """基础过滤:流动性、价格、ST、北交所"""
    initial = len(df)

    # 1. 排除 ST / N / 退市(用 escape 避免 * 被当 regex 处理)
    name_col = '名称'
    import re as _re
    pat = '|'.join(_re.escape(k) for k in EXCLUDE_NAME_KEYWORDS)
    mask = ~df[name_col].astype(str).str.contains(pat, na=False, regex=True)
    df = df[mask].copy()
    # 额外排除首字母 在 EXCLUDE_NAME_PREFIX 中的(次新 N双泰机械)
    if EXCLUDE_NAME_PREFIX:
        df = df[~df[name_col].astype(str).str[0].isin(EXCLUDE_NAME_PREFIX)]
    logger.info(f'  排除 ST/N/退市后: {len(df)} 只')

    # 2. 排除北交所等默认前缀
    code_col = '代码'
    df[code_col] = df[code_col].astype(str).str.lower()
    for prefix in EXCLUDE_CODE_PREFIX:
        df = df[~df[code_col].str.startswith(prefix)]
    # 保留主板/创业板/科创板,能带 sh/sz 前缀或裸代码
    def is_normal_a(code):
        c = str(code).lower().strip()
        # 带前缀版
        if c.startswith('sh') and c[2:].startswith(('60', '68')): return True
        if c.startswith('sz') and c[2:].startswith(('00', '30')): return True
        # 裸代码版(东财热度榜会返回 SH600000 大写,上面已 lower)
        if c.startswith(('60', '68')): return True
        if c.startswith(('00', '30')): return True
        return False
    df = df[df[code_col].apply(is_normal_a)]
    # 统一补 sh/sz 前缀
    def add_prefix(code):
        c = str(code).lower().strip()
        if c.startswith(('sh', 'sz', 'bj')): return c
        if c.startswith(('60', '68')): return 'sh' + c
        if c.startswith(('00', '30')): return 'sz' + c
        return c
    df[code_col] = df[code_col].apply(add_prefix)
    logger.info(f'  排除北交所/异常代码后: {len(df)} 只')

    # 3. 价格 >= 2 元
    if '最新价' in df.columns:
        df = df[df['最新价'] >= MIN_PRICE]
        logger.info(f'  价格 >= ¥{MIN_PRICE} 后: {len(df)} 只')

    # 4. 成交额 >= 5000 万
    if '成交额' in df.columns:
        df = df[df['成交额'] >= MIN_TURNOVER_AMT]
        logger.info(f'  成交额 >= ¥{MIN_TURNOVER_AMT/1e8:.1f}亿 后: {len(df)} 只')

    # 5. 涨跌幅 |x| < 9.5%(避开涨停/跌停)
    if '涨跌幅' in df.columns:
        df = df[df['涨跌幅'].abs() < MAX_DAY_CHANGE]
        logger.info(f'  排除涨跌停后: {len(df)} 只')

    logger.info(f'✓ 基础过滤: {initial} → {len(df)}')
    return df


# =================== 步骤 3: 拉 K 线 + 计算趋势分 ===================
def fetch_kline(code: str, days: int = KLINE_DAYS):
    """拉日 K 线,返回 list of dicts 或 None"""
    import akshare as ak
    # code 是 'sh600000' / 'sz000001'
    sym = str(code).lower().replace('sh', '').replace('sz', '')
    end = date.today().strftime('%Y%m%d')
    start = (date.today() - timedelta(days=days * 2)).strftime('%Y%m%d')  # 多拉点防节假日
    try:
        df = ak.stock_zh_a_hist(symbol=sym, period='daily', start_date=start, end_date=end, adjust='qfq')
        if df is None or len(df) < 30:
            return None
        return df.tail(days).reset_index(drop=True)
    except Exception:
        return None


def calc_score(kline) -> tuple[int, dict]:
    """对一只股票算趋势分,返回 (score, detail)"""
    import pandas as pd
    if kline is None or len(kline) < 25:
        return 0, {}

    closes = kline['收盘'].astype(float).values
    highs = kline['最高'].astype(float).values
    volumes = kline['成交量'].astype(float).values

    last_close = closes[-1]

    # MA 计算
    ma5 = closes[-5:].mean()
    ma10 = closes[-10:].mean()
    ma20 = closes[-20:].mean()

    # 上一日 MA10
    if len(closes) >= 11:
        ma10_prev = closes[-11:-1].mean()
    else:
        ma10_prev = ma10

    # ATR (14)
    atr = 0
    if len(kline) >= 15:
        trs = []
        for i in range(-14, 0):
            tr = max(
                highs[i] - kline['最低'].iloc[i],
                abs(highs[i] - closes[i-1]),
                abs(kline['最低'].iloc[i] - closes[i-1])
            )
            trs.append(tr)
        atr = sum(trs) / len(trs)

    # RSI (14)
    rsi = 50
    if len(closes) >= 15:
        gains, losses = [], []
        for i in range(-14, 0):
            diff = closes[i] - closes[i-1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_g = sum(gains) / 14
        avg_l = sum(losses) / 14
        rsi = 100 if avg_l == 0 else (100 - 100 / (1 + avg_g / avg_l))

    # 20 日成交均量
    vol_avg_20 = volumes[-20:].mean()
    last_vol = volumes[-1]

    # 20 日新高
    n_high_20 = highs[-21:-1].max() if len(highs) > 20 else highs.max()

    # ===== 评分 =====
    score = 0
    detail = {
        'price': float(last_close),
        'ma5': float(ma5),
        'ma10': float(ma10),
        'ma20': float(ma20),
        'rsi': float(rsi),
        'atr': float(atr),
        'vol_ratio': float(last_vol / vol_avg_20) if vol_avg_20 > 0 else 0,
        'n_high_20': float(n_high_20),
        'reasons': [],
    }

    # 1. 多头排列(MA5 > MA10 > MA20)+30
    if ma5 > ma10 > ma20:
        score += 30
        detail['reasons'].append('多头排列')

    # 2. 量能放大 +20
    if vol_avg_20 > 0 and last_vol >= vol_avg_20 * 1.5:
        score += 20
        detail['reasons'].append(f'量{last_vol/vol_avg_20:.1f}x')

    # 3. 突破 20 日新高 +25
    if last_close > n_high_20:
        score += 25
        detail['reasons'].append(f'破{n_high_20:.2f}新高')
    elif last_close > n_high_20 * 0.97:
        score += 12
        detail['reasons'].append(f'近新高')

    # 4. RSI 50-70(强势但不超买)+15
    if 50 <= rsi <= 70:
        score += 15
        detail['reasons'].append(f'RSI{rsi:.0f}')
    elif 70 < rsi <= 80:
        score += 5  # 过热但还能玩

    # 5. 站上 MA10 +10
    if last_close > ma10:
        score += 10
        detail['reasons'].append('站上MA10')

    # 6. 价格高于 MA20(趋势向上)+10
    if last_close > ma20:
        score += 10

    detail['score'] = score
    return score, detail


# =================== 步骤 4: 主扫描流程 ===================
def scan_market():
    df = fetch_market_snapshot()
    df = basic_filter(df)

    # 取 top N（按成交额）
    if '成交额' in df.columns:
        df = df.nlargest(TOP_N_FOR_KLINE, '成交额').reset_index(drop=True)
    else:
        df = df.head(TOP_N_FOR_KLINE).reset_index(drop=True)
    logger.info(f'\n=== 对 top {len(df)} 只股票拉 K 线扫描 ===')

    candidates = []
    for i, row in df.iterrows():
        code = str(row['代码'])  # sh600000 格式
        name = str(row['名称'])
        if (i+1) % 20 == 0:
            logger.info(f'  扫描进度 {i+1}/{len(df)}...')

        kline = fetch_kline(code)
        if kline is None:
            continue
        score, detail = calc_score(kline)
        if score >= SCORE_THRESHOLD:
            candidates.append({
                'code': code[2:],  # 去掉 sh/sz 前缀
                'symbol_full': code,
                'name': name,
                'score': score,
                'price': detail['price'],
                'ma10': detail['ma10'],
                'ma20': detail['ma20'],
                'atr': detail['atr'],
                'rsi': detail['rsi'],
                'vol_ratio': detail['vol_ratio'],
                'reasons': detail['reasons'],
                'turnover_amt': float(row['成交额']),
                'change_pct': float(row['涨跌幅']),
            })
        time.sleep(0.05)  # 不给数据源加压

    candidates.sort(key=lambda x: x['score'], reverse=True)
    logger.info(f'\n✓ 候选股 {len(candidates)} 只(评分 >= {SCORE_THRESHOLD})')
    return candidates


# =================== 步骤 5: 写报告 ===================
def write_report(candidates, scan_date):
    md_lines = [f'# 🔍 全市场扫描报告 {scan_date}\n']
    md_lines.append(f'扫描时间: {datetime.now():%Y-%m-%d %H:%M:%S}')
    md_lines.append(f'候选股: **{len(candidates)}** 只 (评分阈值 {SCORE_THRESHOLD})')
    md_lines.append(f'入池数: top **{TOP_N_TO_POOL}**')
    md_lines.append('\n---\n')

    md_lines.append('## 🏆 Top 候选\n')
    md_lines.append('| 排名 | 代码 | 名称 | 现价 | 涨跌% | 评分 | 量比 | RSI | 信号 |')
    md_lines.append('|---|---|---|---|---|---|---|---|---|')
    for i, c in enumerate(candidates[:TOP_N_TO_POOL * 2], 1):  # 多列点
        md_lines.append(
            f"| {i} | {c['code']} | {c['name']} | ¥{c['price']:.2f} | "
            f"{c['change_pct']:+.2f}% | **{c['score']}** | "
            f"{c['vol_ratio']:.1f}x | {c['rsi']:.0f} | {' / '.join(c['reasons'])} |"
        )

    md_path = OUT_DIR / f'{scan_date}.md'
    md_path.write_text('\n'.join(md_lines), encoding='utf-8')
    logger.info(f'✓ 报告: {md_path}')

    json_path = OUT_DIR / f'{scan_date}.json'
    json_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info(f'✓ JSON: {json_path}')


# =================== 步骤 6: 更新 config.yaml ===================
def update_watchlist(candidates, scan_date):
    """把 top N 候选加入 config.yaml watchlist,标 source=auto_scanner
    保留人工添加的(玄鉴录/涛哥推荐等),只更新 auto_scanner 那部分
    """
    if os.environ.get('DRY_RUN') == '1':
        logger.info('🟡 DRY_RUN=1,不改 config.yaml')
        return 0, 0

    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding='utf-8')) or {}
    watchlist = cfg.setdefault('watchlist', {}) or {}

    # 1. 移除旧的 auto_scanner(30 天前的或者今天扫不到的)
    removed = []
    keep_codes = set(c['code'] for c in candidates[:TOP_N_TO_POOL])
    for code in list(watchlist.keys()):
        body = watchlist[code]
        if not isinstance(body, dict):
            continue
        if body.get('source') == 'auto_scanner' and code not in keep_codes:
            # 检查是否过期(>= 30 天)
            added = body.get('added_at', '2000-01-01')
            try:
                age_days = (date.today() - date.fromisoformat(str(added))).days
            except Exception:
                age_days = 999
            if age_days >= 30 or code not in keep_codes:
                removed.append(code)
                del watchlist[code]

    # 2. 加入新候选
    added = []
    for c in candidates[:TOP_N_TO_POOL]:
        code = c['code']
        if code in watchlist:
            # 已存在(人工或之前 auto),更新 reason 但不覆盖 source
            existing = watchlist[code]
            if existing.get('source') == 'auto_scanner':
                existing['added_at'] = str(scan_date)
                existing['added_reason'] = f"扫描分 {c['score']}: {' / '.join(c['reasons'])}"
                existing['added_price'] = c['price']
            continue

        # 新加(标 strategy:trend,让趋势策略接管)
        # buy_zone: 现价 × 0.97(回调 3% 触发买入)
        # trend_break: max(MA20×0.95, ATR 止损)
        # take_profit: 现价 × 1.15(涨 15% 部分止盈)
        watchlist[code] = {
            'name': c['name'],
            'enabled': True,
            'source': 'auto_scanner',
            'strategy': 'trend',
            'added_at': str(scan_date),
            'added_price': round(c['price'], 2),
            'added_reason': f"扫描分 {c['score']}: {' / '.join(c['reasons'])}",
            'tags': ['自动扫描', '趋势'],
            'rules': {
                'buy_zone': round(c['price'] * 0.97, 2),
                'buy_strong': round(c['price'] * 0.93, 2),
                'trend_break': round(min(c['ma20'] * 0.95, c['price'] - c['atr'] * 2), 2),
                'take_profit': round(c['price'] * 1.15, 2),
            }
        }
        added.append((code, c['name'], c['score']))

    # 3. 写回(保留备份)
    backup = CONFIG_PATH.parent / f"config.yaml.bak.{datetime.now():%Y%m%d_%H%M%S}"
    backup.write_text(CONFIG_PATH.read_text(encoding='utf-8'), encoding='utf-8')
    CONFIG_PATH.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding='utf-8'
    )
    logger.info(f'✓ config.yaml 已更新(备份: {backup.name})')
    logger.info(f'  +{len(added)} 新增, -{len(removed)} 移除')
    return len(added), len(removed)


# =================== 步骤 7: 推送企微 ===================
def push_summary(candidates, n_added, n_removed, scan_date):
    if os.environ.get('PUSH', '').lower() not in ('1', 'true', 'yes'):
        logger.info('未设 PUSH=1,跳过推送')
        return

    cfg = load_config()
    webhook = (cfg.get('notifier') or {}).get('wecom_webhook', '')
    if not webhook:
        logger.warning('webhook 未配置')
        return

    lines = [f"# 🔍 {scan_date} 全市场扫描\n"]
    lines.append(f"候选 **{len(candidates)}** 只 / 入池 top **{TOP_N_TO_POOL}**")
    lines.append(f"📊 +{n_added} 新增 / -{n_removed} 移除\n")
    lines.append(f"## 🏆 Top {min(10, TOP_N_TO_POOL)} 入池")
    for i, c in enumerate(candidates[:min(10, TOP_N_TO_POOL)], 1):
        lines.append(
            f"{i}. **{c['name']}** ({c['code']}) ¥{c['price']:.2f} "
            f"评分 **{c['score']}** [{' / '.join(c['reasons'][:3])}]"
        )
    if len(candidates) > 10:
        lines.append(f"\n... 还有 {min(len(candidates), TOP_N_TO_POOL) - 10} 只")
    lines.append(f"\n_周一 9:25 vqlearn 自动加载新观察池_")

    content = '\n'.join(lines)
    try:
        resp = requests.post(webhook, json={
            'msgtype': 'markdown', 'markdown': {'content': content}
        }, timeout=8)
        ok = resp.json().get('errcode') == 0
        logger.info(f'推送 {"成功" if ok else "失败"}: {resp.text[:120]}')
    except Exception as e:
        logger.error(f'推送异常: {e}')


# =================== 主入口 ===================
def main():
    scan_date = date.today().isoformat()
    logger.info(f'=== 全市场扫描 {scan_date} ===')

    candidates = scan_market()
    if not candidates:
        logger.warning('无候选股,退出')
        return

    write_report(candidates, scan_date)
    n_added, n_removed = update_watchlist(candidates, scan_date)
    push_summary(candidates, n_added, n_removed, scan_date)

    logger.info(f'\n=== 完成 ===')
    logger.info(f'候选 {len(candidates)} | 入池 top {TOP_N_TO_POOL} | +{n_added}/-{n_removed}')


if __name__ == '__main__':
    main()
