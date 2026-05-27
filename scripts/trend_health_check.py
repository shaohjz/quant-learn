"""
\u626b\u63cf\u5168 watchlist \u80a1\u7968\u7684\u8d8b\u52bf\u5065\u5eb7\u72b6\u6001\uff1a
- MA20 vs MA60 \u662f\u5426\u591a\u5934\u6392\u5217
- last vs MA60 \u662f\u5426\u7ad9\u4e0a
- MACD \u662f\u5426\u91d1\u53c9\uff08DIF > DEA \u4e14 DIF > 0 \u4e3a\u53f3\u4fa7\u786e\u8ba4\uff09

\u8f93\u51fa\u4e09\u6863\u5206\u7c7b\uff1a
- HEALTHY: \u591a\u5934\u6392\u5217 + last \u4e0a MA60 + MACD\u91d1\u53c9 \u2192 buy \u4fe1\u53f7\u53ef\u7528
- WEAK:    last \u4e0a MA60 \u4f46 MA20 \u4e0b MA60 \u6216 MACD \u672a\u91d1\u53c9 \u2192 buy \u4fe1\u53f7\u8c28\u614e
- BROKEN:  last \u4e0b MA60 \u2192 \u51bb\u7ed3 buy \u4fe1\u53f7\uff0c\u7b49\u53f3\u4fa7\u786e\u8ba4
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
        'date,close',
        start_date=start, end_date=end,
        frequency='d', adjustflag='2'
    )
    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(rows, columns=rs.fields)
    df['close'] = pd.to_numeric(df['close'], errors='coerce')
    return df.dropna()


def calc_macd(closes: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    return dif, dea


def analyze(code: str, name: str):
    df = fetch_kline(code, days=90)
    if len(df) < 60:
        return None
    closes = df['close']
    last = float(closes.iloc[-1])
    ma10 = float(closes.rolling(10).mean().iloc[-1])
    ma20 = float(closes.rolling(20).mean().iloc[-1])
    ma60 = float(closes.rolling(60).mean().iloc[-1])
    dif, dea = calc_macd(closes)
    dif_now, dea_now = float(dif.iloc[-1]), float(dea.iloc[-1])
    dif_prev, dea_prev = float(dif.iloc[-2]), float(dea.iloc[-2])

    # MACD \u91d1\u53c9\u5224\u65ad
    macd_golden = dif_now > dea_now  # \u591a\u5934
    macd_just_crossed = (dif_now > dea_now) and (dif_prev <= dea_prev)  # \u4eca\u65e5\u521a\u91d1\u53c9
    dif_above_zero = dif_now > 0  # \u5f3a\u52bf\u533a\uff08\u96f6\u8f74\u4e0a\u65b9\uff09

    # \u8d8b\u52bf\u5206\u7c7b
    if last < ma60:
        status = 'BROKEN'  # \u8df3\u7834 MA60
    elif ma20 < ma60:
        status = 'WEAK'    # last \u4e0a MA60 \u4f46\u5747\u7ebf\u8fd8\u662f\u7a7a\u5934\u6392\u5217
    elif macd_golden and dif_above_zero:
        status = 'HEALTHY' # \u591a\u5934\u6392\u5217 + MACD \u53cc\u5934\u4e0a
    elif macd_golden:
        status = 'OK'      # \u5747\u7ebf\u591a\u5934\u4f46 MACD \u8fd8\u5728 0 \u4e0b
    else:
        status = 'CAUTION' # \u5747\u7ebf\u591a\u5934\u4f46 MACD \u672a\u91d1\u53c9

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
                    print(f"  {r['status']:8s} {code} {r['name']:6s} last={r['last']:>7.2f} "
                          f"MA60={r['ma60']:>7.2f} (last/ma60 {r['last_vs_ma60_pct']:+.1f}%) "
                          f"DIF={r['dif']:.2f} DEA={r['dea']:.2f} {'\u91d1\u53c9' if r['macd_golden'] else '\u6b7b\u53c9'}"
                          f"{' \u26a1\u4eca\u91d1\u53c9' if r['macd_just_crossed'] else ''}"
                          f"{' (\u51bb\u7ed3\u4e2d)' if r['auto_buy_disabled'] else ''}")
            except Exception as e:
                print(f"  ERROR {code}: {e}")
    finally:
        bs.logout()

    # \u5206\u6863\u6c47\u603b
    print('\n=== Summary ===')
    by_status = {}
    for r in results:
        by_status.setdefault(r['status'], []).append(r)
    for status in ['HEALTHY', 'OK', 'CAUTION', 'WEAK', 'BROKEN']:
        items = by_status.get(status, [])
        if items:
            print(f'\n[{status}] ({len(items)} \u53ea):')
            for r in items:
                tag = ' \u26a1\u521a\u91d1\u53c9' if r['macd_just_crossed'] else ''
                disabled = ' \u26a0disabled' if r['auto_buy_disabled'] else ''
                print(f"  {r['code']} {r['name']:6s} | last \u00a5{r['last']:.2f} | MA60 \u00a5{r['ma60']:.2f} "
                      f"({r['last_vs_ma60_pct']:+.1f}%) | DIF {r['dif']:+.3f}{tag}{disabled}")

    # \u8f93\u51fa JSON \u4f9b\u811a\u672c\u5904\u7406
    from datetime import date as _date
    out = Path(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\output') / f'trend_health_{_date.today().isoformat()}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    import json
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\nSaved: {out}')


if __name__ == '__main__':
    main()
