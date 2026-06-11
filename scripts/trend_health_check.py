"""
扫描全 watchlist 股票的趋势健康状态。

判据（5 个维度）：
  1. MA20 vs MA60 是否多头排列
  2. last vs MA60 是否站上
  3. MACD 是否金叉（DIF > DEA 且 DIF > 0 为右侧确认）
  4. ⚡ 量能：MACD 金叉/将金叉时，最近 3 日均量 vs 过去 20 日均量（>1.0 才算有效金叉）
  5. ⚡ 波动率：ATR(14) / 收盘价 < 8%（避免在剧烈波动股上信任 MA60）

输出五档分类：
- HEALTHY: 多头排列 + last 上 MA60 + MACD金叉 + 量能放大 + 波动率正常 → buy 信号最可信
- OK:      多头排列 + MACD金叉但 DIF<0 OR 量能不放大 → buy 可用但保守
- CAUTION: 均线多头但 MACD 未金叉 → 等右侧确认
- WEAK:    last 上 MA60 但 MA20 < MA60 → 均线还空头
- BROKEN:  last 下 MA60 → 冻结 buy 信号
- DIRTY:   ATR/价格 > 8% 或样本不足 → 数据脏，trend_filter 不可信
"""
import baostock as bs
import pandas as pd
import yaml
from datetime import datetime, timedelta
from pathlib import Path

CONFIG = Path(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\config.yaml')


def code_with_prefix(code: str) -> str:
    return f'sh.{code}' if code.startswith('6') else f'sz.{code}'


def fetch_kline(code: str, days: int = 90):
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=days*2)).strftime('%Y-%m-%d')
    rs = bs.query_history_k_data_plus(
        code_with_prefix(code),
        'date,open,high,low,close,volume',
        start_date=start, end_date=end,
        frequency='d', adjustflag='2'
    )
    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(rows, columns=rs.fields)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df.dropna()


def calc_macd(closes: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    return dif, dea


def calc_atr(df: pd.DataFrame, period: int = 14):
    """真实波幅。最近 period 日的 max(high-low, |high-prev_close|, |low-prev_close|) 平均"""
    high, low, close = df['high'], df['low'], df['close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def analyze(code: str, name: str):
    df = fetch_kline(code, days=90)
    if len(df) < 60:
        return None
    closes = df['close']
    volumes = df['volume']
    last = float(closes.iloc[-1])
    ma10 = float(closes.rolling(10).mean().iloc[-1])
    ma20 = float(closes.rolling(20).mean().iloc[-1])
    ma60 = float(closes.rolling(60).mean().iloc[-1])
    dif, dea = calc_macd(closes)
    dif_now, dea_now = float(dif.iloc[-1]), float(dea.iloc[-1])
    dif_prev, dea_prev = float(dif.iloc[-2]), float(dea.iloc[-2])

    # MACD 状态
    macd_golden = dif_now > dea_now
    macd_just_crossed = (dif_now > dea_now) and (dif_prev <= dea_prev)
    dif_above_zero = dif_now > 0

    # ⚡ 量能确认：最近 3 日均量 vs 过去 20 日均量（剔除最近 3 日）
    vol_recent3 = float(volumes.iloc[-3:].mean())
    vol_baseline20 = float(volumes.iloc[-23:-3].mean()) if len(volumes) >= 23 else float(volumes.iloc[:-3].mean())
    vol_ratio = (vol_recent3 / vol_baseline20) if vol_baseline20 > 0 else 0.0
    vol_confirmed = vol_ratio >= 1.0  # 不缩量
    vol_strong = vol_ratio >= 1.3      # 明显放量

    # ⚡ ATR 波动率
    atr_series = calc_atr(df, 14)
    atr14 = float(atr_series.iloc[-1]) if not atr_series.iloc[-1] != atr_series.iloc[-1] else 0.0  # NaN check
    atr_pct = (atr14 / last * 100) if last > 0 else 0.0
    is_dirty = atr_pct > 8.0 or len(df) < 60  # 波动太大数据不可信

    # 趋势分类
    if is_dirty:
        status = 'DIRTY'
    elif last < ma60:
        status = 'BROKEN'
    elif ma20 < ma60:
        status = 'WEAK'
    elif macd_golden and dif_above_zero and vol_confirmed:
        # ⚡ 升级：必须 量能配合 才能算 HEALTHY
        status = 'HEALTHY'
    elif macd_golden and dif_above_zero:
        # 金叉但量能不配 → OK
        status = 'OK_NO_VOL'
    elif macd_golden:
        status = 'OK'  # 金叉但 DIF < 0
    else:
        status = 'CAUTION'

    return {
        'code': code, 'name': name,
        'last': round(last, 2), 'ma10': round(ma10, 2),
        'ma20': round(ma20, 2), 'ma60': round(ma60, 2),
        'last_vs_ma60_pct': round((last - ma60) / ma60 * 100, 1),
        'ma20_vs_ma60_pct': round((ma20 - ma60) / ma60 * 100, 1),
        'dif': round(dif_now, 3), 'dea': round(dea_now, 3),
        'macd_golden': macd_golden,
        'macd_just_crossed': macd_just_crossed,
        'dif_above_zero': dif_above_zero,
        'vol_ratio': round(vol_ratio, 2),
        'vol_confirmed': vol_confirmed,
        'vol_strong': vol_strong,
        'atr14': round(atr14, 3),
        'atr_pct': round(atr_pct, 2),
        'is_dirty': is_dirty,
        'status': status,
    }


def main():
    cfg = yaml.safe_load(CONFIG.read_text(encoding='utf-8'))
    wm = cfg['watchlist']['user_manual']

    print('Logging into BaoStock...')
    bs.login()
    try:
        results = []
        for code, info in wm.items():
            if not info.get('enabled', True):
                continue
            try:
                r = analyze(code, info.get('name', ''))
                if r:
                    r['source'] = info.get('source', '')
                    r['auto_buy_disabled'] = info.get('auto_buy_disabled', False)
                    results.append(r)
                    vol_tag = f"vol×{r['vol_ratio']:.1f}"
                    atr_tag = f"ATR{r['atr_pct']:.1f}%"
                    print(f"  {r['status']:10s} {code} {r['name']:6s} last={r['last']:>7.2f} "
                          f"MA60={r['ma60']:>7.2f} ({r['last_vs_ma60_pct']:+.1f}%) "
                          f"DIF={r['dif']:.2f} {'金叉' if r['macd_golden'] else '死叉'} "
                          f"{vol_tag} {atr_tag}"
                          f"{' ⚡今金叉' if r['macd_just_crossed'] else ''}"
                          f"{' (冻结)' if r['auto_buy_disabled'] else ''}")
            except Exception as e:
                print(f"  ERROR {code}: {e}")
    finally:
        bs.logout()

    # 分档汇总
    print('\n=== Summary ===')
    by_status = {}
    for r in results:
        by_status.setdefault(r['status'], []).append(r)
    for status in ['HEALTHY', 'OK', 'OK_NO_VOL', 'CAUTION', 'WEAK', 'BROKEN', 'DIRTY']:
        items = by_status.get(status, [])
        if items:
            print(f'\n[{status}] ({len(items)} 只):')
            for r in items:
                tag = ' ⚡刚金叉' if r['macd_just_crossed'] else ''
                disabled = ' ⚠disabled' if r['auto_buy_disabled'] else ''
                print(f"  {r['code']} {r['name']:6s} | last ¥{r['last']:.2f} | MA60 ¥{r['ma60']:.2f} "
                      f"({r['last_vs_ma60_pct']:+.1f}%) | DIF {r['dif']:+.3f} | "
                      f"vol×{r['vol_ratio']:.2f} | ATR {r['atr_pct']:.2f}%{tag}{disabled}")

    # 输出 JSON
    from datetime import date as _date
    out = Path(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\output') / f'trend_health_{_date.today().isoformat()}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    import json
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\nSaved: {out}')


if __name__ == '__main__':
    main()
