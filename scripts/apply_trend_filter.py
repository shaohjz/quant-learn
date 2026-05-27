"""
根据趋势健康检查结果，给 watchlist 里所有股票加上 trend_filter 字段。

设计：
- 保留原始 buy_zone/buy_strong（以防趋势修复后手工解冻）
- 新增字段 trend_filter:
  - {gate: 'auto'}         → 默认，sim_executor 邀 buy
  - {gate: 'wait_volume'}  → 金叉但缩量，需要量能放大才买（OK_NO_VOL）
  - {gate: 'wait_macd'}    → 只有当 MACD 金叉且 DIF>0 才买（CAUTION）
  - {gate: 'manual_only'}  → 不自动买，仅推送人工提醒（WEAK / DIRTY）
  - {gate: 'frozen'}       → 移除 buy_zone/buy_strong 只留右侧确认 trigger（BROKEN）

同时在 sim_executor 里加处理逻辑。
"""
import json
import yaml
from datetime import date
from pathlib import Path

ROOT = Path(r'C:\Users\Administrator\.openclaw\workspace\quant-learn')
CONFIG = ROOT / 'config.yaml'


def _find_latest_health() -> Path:
    today_path = ROOT / 'output' / f'trend_health_{date.today().isoformat()}.json'
    if today_path.exists():
        return today_path
    candidates = sorted((ROOT / 'output').glob('trend_health_*.json'))
    if candidates:
        return candidates[-1]
    raise FileNotFoundError('No trend_health_*.json found, run trend_health_check.py first')


HEALTH = _find_latest_health()

# 状态 -> trend_filter
STATUS_TO_GATE = {
    'HEALTHY': 'auto',
    'OK': 'auto',                # 金叉但 DIF<0，仍让买
    'OK_NO_VOL': 'wait_volume',  # 金叉 DIF>0 但缩量 → 等量能放大
    'CAUTION': 'wait_macd',
    'WEAK': 'manual_only',
    'BROKEN': 'frozen',
    'DIRTY': 'manual_only',      # ATR 过高，趋势信号不可信
}


def main():
    cfg = yaml.safe_load(CONFIG.read_text(encoding='utf-8'))
    health = {r['code']: r for r in json.loads(HEALTH.read_text(encoding='utf-8'))}
    wm = cfg['watchlist']['user_manual']

    print(f'Total watchlist: {len(wm)}\n')
    summary = {'auto': [], 'require_support': [], 'wait_volume': [], 'wait_macd': [], 'manual_only': [], 'frozen': [], 'skipped': []}

    for code, info in wm.items():
        # 跳过手动 disabled 的（如电信）
        if info.get('auto_buy_disabled'):
            summary['skipped'].append((code, info['name'], 'manually disabled'))
            continue
        if code not in health:
            summary['skipped'].append((code, info.get('name', ''), 'no health data'))
            continue

        h = health[code]
        gate = STATUS_TO_GATE[h['status']]

        info['trend_filter'] = {
            'gate': gate,
            'status': h['status'],
            'last': h['last'],
            'ma60': h['ma60'],
            'last_vs_ma60_pct': h['last_vs_ma60_pct'],
            'ma20_vs_ma60_pct': h['ma20_vs_ma60_pct'],
            'macd_golden': h['macd_golden'],
            'vol_ratio': h.get('vol_ratio'),
            'atr_pct': h.get('atr_pct'),
            'updated_at': date.today().isoformat(),
        }

        # frozen：移除 buy_zone/buy_strong + 加右侧确认
        if gate == 'frozen':
            old_rules = info.get('rules', {})
            backup = {k: v for k, v in old_rules.items() if k in ('buy_zone', 'buy_strong')}
            backup_key = f'rules_backup_{date.today().isoformat()}'
            if backup and backup_key not in info:
                info[backup_key] = backup
            new_rules = {k: v for k, v in old_rules.items() if k not in ('buy_zone', 'buy_strong')}
            new_rules['right_side_confirm'] = {
                'trigger': round(h['ma60'] * 1.02, 2),
                'dir': 'above',
                'msg': f"✅ {info['name']}站上 {h['ma60'] * 1.02:.2f} (MA60×1.02)！右侧确认信号，可考虑解冻",
            }
            new_rules['trend_break_warn'] = {
                'trigger': round(h['ma60'] * 0.95, 2),
                'dir': 'below',
                'msg': f"⚠️ {info['name']}跳破 {h['ma60'] * 0.95:.2f} (MA60×0.95)！趋势实质走坏",
            }
            info['rules'] = new_rules

        summary[gate].append((code, info['name'], h))

    # 写回
    CONFIG.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding='utf-8'
    )

    # 报告
    print('=' * 70)
    print('整改总结')
    print('=' * 70)
    for gate in ['auto', 'require_support', 'wait_volume', 'wait_macd', 'manual_only', 'frozen']:
        items = summary[gate]
        gate_desc = {
            'auto':            '✅ auto            — 健康多头 + MACD金叉 + 量能配合，正常自动买入',
            'require_support': '🔍 require_support — 左侧低吸，需价位在支撑区 + 量能企稳+启动信号才买',
            'wait_volume':     '📊 wait_volume     — 金叉但缩量，等量能放大（暂时拦截）',
            'wait_macd':       '⏳ wait_macd       — 均线多头但 MACD 未金叉，等右侧确认',
            'manual_only':     '✋ manual_only     — 均线还空头 或 ATR过高，仅提醒不自动',
            'frozen':          '⛔ frozen          — last<MA60 趋势已坏，冻结买入 加右侧确认',
        }[gate]
        print(f'\n{gate_desc} ({len(items)}只):')
        for code, name, h in items:
            extra = f" | vol×{h.get('vol_ratio', 0):.2f} | ATR{h.get('atr_pct', 0):.1f}%"
            print(f"  {code} {name:6s} | last¥{h['last']:.2f} | MA60¥{h['ma60']:.2f} "
                  f"({h['last_vs_ma60_pct']:+.1f}%) | MACD{'金叉' if h['macd_golden'] else '死叉'}{extra}")
    if summary['skipped']:
        print(f'\n[skipped] ({len(summary["skipped"])}):')
        for code, name, reason in summary['skipped']:
            print(f'  {code} {name} ({reason})')

    print('\nconfig.yaml 已更新。')


if __name__ == '__main__':
    main()
