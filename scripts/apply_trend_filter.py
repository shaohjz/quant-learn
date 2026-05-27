"""
\u6839\u636e\u8d8b\u52bf\u5065\u5eb7\u68c0\u67e5\u7ed3\u679c\uff0c\u7ed9 watchlist \u91cc\u6240\u6709\u80a1\u7968\u52a0\u4e0a trend_filter \u5b57\u6bb5\u3002

\u8bbe\u8ba1\uff1a
- \u4fdd\u7559\u539f\u59cb buy_zone/buy_strong\uff08\u4ee5\u9632\u8d8b\u52bf\u4fee\u590d\u540e\u624b\u5de5\u89e3\u51bb\uff09
- \u65b0\u589e\u5b57\u6bb5 trend_filter\uff1a
  - {gate: 'auto'}        \u2192 \u9ed8\u8ba4\uff0csim_executor \u9080 buy
  - {gate: 'wait_macd'}   \u2192 \u53ea\u6709\u5f53 MACD \u91d1\u53c9\u4e14 DIF>0 \u624d\u4e70\uff08CAUTION \u53ea\u80a1\uff09
  - {gate: 'manual_only'} \u2192 \u4e0d\u81ea\u52a8\u4e70\uff0c\u4ec5\u63a8\u9001\u4eba\u5de5\u63d0\u9192\uff08WEAK\uff09
  - {gate: 'frozen'}      \u2192 \u79fb\u9664 buy_zone/buy_strong \u53ea\u7559\u53f3\u4fa7\u786e\u8ba4 trigger\uff08BROKEN\uff09

\u540c\u65f6\u5728 sim_executor \u91cc\u52a0\u5904\u7406\u903b\u8f91\u3002
"""
import json
import yaml
from datetime import date
from pathlib import Path

ROOT = Path(r'C:\Users\Administrator\.openclaw\workspace\quant-learn')
CONFIG = ROOT / 'config.yaml'


def _find_latest_health() -> Path:
    """先找今日，找不到则取最近一份"""
    today_path = ROOT / 'output' / f'trend_health_{date.today().isoformat()}.json'
    if today_path.exists():
        return today_path
    candidates = sorted((ROOT / 'output').glob('trend_health_*.json'))
    if candidates:
        return candidates[-1]
    raise FileNotFoundError('No trend_health_*.json found, run trend_health_check.py first')


HEALTH = _find_latest_health()

# \u72b6\u6001 -> trend_filter
STATUS_TO_GATE = {
    'HEALTHY': 'auto',
    'OK': 'auto',
    'CAUTION': 'wait_macd',
    'WEAK': 'manual_only',
    'BROKEN': 'frozen',
}


def main():
    cfg = yaml.safe_load(CONFIG.read_text(encoding='utf-8'))
    health = {r['code']: r for r in json.loads(HEALTH.read_text(encoding='utf-8'))}
    wm = cfg['watchlist']['user_manual']

    print(f'Total watchlist: {len(wm)}\n')
    summary = {'auto': [], 'wait_macd': [], 'manual_only': [], 'frozen': [], 'skipped': []}

    for code, info in wm.items():
        # \u8df3\u8fc7\u624b\u52a8 disabled \u7684\uff08\u5982\u7535\u4fe1\uff09
        if info.get('auto_buy_disabled'):
            summary['skipped'].append((code, info['name'], 'manually disabled'))
            continue
        if code not in health:
            summary['skipped'].append((code, info.get('name', ''), 'no health data'))
            continue

        h = health[code]
        gate = STATUS_TO_GATE[h['status']]

        # \u4fdd\u5b58\u8bca\u65ad\u4fe1\u606f\u8fdb yaml\uff08\u4eba\u53ef\u8bfb\uff09
        info['trend_filter'] = {
            'gate': gate,
            'status': h['status'],
            'last': h['last'],
            'ma60': h['ma60'],
            'last_vs_ma60_pct': h['last_vs_ma60_pct'],
            'ma20_vs_ma60_pct': h['ma20_vs_ma60_pct'],
            'macd_golden': h['macd_golden'],
            'updated_at': '2026-05-27',
        }

        # frozen \u7684\u80a1\uff1a\u79fb\u9664 buy_zone/buy_strong\uff0c\u5907\u4efd\u5230 rules_backup
        if gate == 'frozen':
            old_rules = info.get('rules', {})
            backup = {k: v for k, v in old_rules.items() if k in ('buy_zone', 'buy_strong')}
            if backup:
                info['rules_backup_2026-05-27'] = backup
            new_rules = {k: v for k, v in old_rules.items() if k not in ('buy_zone', 'buy_strong')}
            # \u52a0\u53f3\u4fa7\u786e\u8ba4
            new_rules['right_side_confirm'] = {
                'trigger': round(h['ma60'] * 1.02, 2),
                'dir': 'above',
                'msg': f"\u2705 {info['name']}\u7ad9\u4e0a {h['ma60'] * 1.02:.2f} (MA60\u00d71.02)\uff01\u53f3\u4fa7\u786e\u8ba4\u4fe1\u53f7\uff0c\u53ef\u8003\u8651\u89e3\u51bb",
            }
            new_rules['trend_break_warn'] = {
                'trigger': round(h['ma60'] * 0.95, 2),
                'dir': 'below',
                'msg': f"\u26a0\ufe0f {info['name']}\u8df3\u7834 {h['ma60'] * 0.95:.2f} (MA60\u00d70.95)\uff01\u8d8b\u52bf\u5b9e\u8d28\u8d70\u574f",
            }
            info['rules'] = new_rules

        summary[gate].append((code, info['name'], h))

    # \u5199\u56de
    CONFIG.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding='utf-8'
    )

    # \u62a5\u544a
    print('=' * 70)
    print('\u6574\u6539\u603b\u7ed3')
    print('=' * 70)
    for gate in ['auto', 'wait_macd', 'manual_only', 'frozen']:
        items = summary[gate]
        gate_desc = {
            'auto': '\u2705 auto \u2014 \u5065\u5eb7\u591a\u5934 + MACD\u91d1\u53c9\uff0c\u6b63\u5e38\u81ea\u52a8\u4e70\u5165',
            'wait_macd': '\u23f3 wait_macd \u2014 \u5747\u7ebf\u591a\u5934\u4f46 MACD \u672a\u91d1\u53c9\uff0c\u7b49\u53f3\u4fa7\u786e\u8ba4',
            'manual_only': '\u270b manual_only \u2014 MA20<MA60 \u5747\u7ebf\u8fd8\u7a7a\u5934\uff0c\u4ec5\u63d0\u9192\u4e0d\u81ea\u52a8',
            'frozen': '\u26d4 frozen \u2014 last<MA60 \u8d8b\u52bf\u5df2\u574f\uff0c\u51bb\u7ed3\u4e70\u5165 \u52a0\u53f3\u4fa7\u786e\u8ba4',
        }[gate]
        print(f'\n{gate_desc} ({len(items)}\u53ea):')
        for code, name, h in items:
            print(f"  {code} {name:6s} | last\u00a5{h['last']:.2f} | MA60\u00a5{h['ma60']:.2f} ({h['last_vs_ma60_pct']:+.1f}%) | MACD{'\u91d1\u53c9' if h['macd_golden'] else '\u6b7b\u53c9'}")
    if summary['skipped']:
        print(f'\n[skipped] ({len(summary["skipped"])}):')
        for code, name, reason in summary['skipped']:
            print(f'  {code} {name} ({reason})')

    print('\nconfig.yaml \u5df2\u66f4\u65b0\u3002')


if __name__ == '__main__':
    main()
