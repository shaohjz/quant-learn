import sys
from pathlib import Path
ROOT = Path(r'C:\Users\Administrator\.openclaw\workspace\quant-learn')
sys.path.insert(0, str(ROOT / 'scripts'))

from morning_scanner import calc_factors, get_kline
import baostock as bs

bs.login()
try:
    # 选 3 个典型例子: HEALTHY / BROKEN / DIRTY
    for code, label in [('000725', '京东方A HEALTHY'), ('600309', '万华化学 BROKEN'), ('603757', '大元泵业 DIRTY')]:
        df = get_kline(code, days=70)
        if df is None:
            print(f'{code}: no data')
            continue
        result = calc_factors(code, df, None)
        if result:
            ma60 = result.get('ma60')
            ma60_str = f"{ma60:.2f}" if ma60 else "-"
            print(f"{code} {label} | score={result['score']} | mult={result['trend_quality_mult']:.2f} | "
                  f"ma60={ma60_str} | ATR={result['atr_pct']:.2f}% | "
                  f"factors={result['factors']}")
finally:
    bs.logout()
