"""
scripts/watchlist_stats.py — 观察池来源统计
按 source / recommended_by / tags 分组统计
也可作为复盘报告附录
"""
from __future__ import annotations
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sim.config import load_config


def main():
    load_config.cache_clear()
    cfg = load_config()
    wl = cfg.get('watchlist', {}) or {}

    print('=' * 70)
    print(f'📊 观察池来源统计 (总 {len(wl)} 只)')
    print('=' * 70)

    # 1. 按 source 分组
    by_source = defaultdict(list)
    for code, body in wl.items():
        src = body.get('source') or 'unknown'
        by_source[src].append((code, body.get('name', ''), body.get('added_at', '')))

    print('\n## 按来源分组')
    print('-' * 70)
    for src in sorted(by_source.keys()):
        items = by_source[src]
        print(f'\n  📍 {src}  ({len(items)} 只)')
        for code, name, added in items:
            print(f'     - {code} {name:<8} (加入: {added})')

    # 2. 按 recommended_by 分组（个人推荐者）
    by_rec = defaultdict(list)
    for code, body in wl.items():
        rec = body.get('recommended_by')
        if rec:
            by_rec[rec].append((code, body.get('name', ''), body.get('added_at', '')))

    if by_rec:
        print('\n\n## 按推荐人分组（个人）')
        print('-' * 70)
        for rec in sorted(by_rec.keys()):
            items = by_rec[rec]
            print(f'\n  👤 {rec}  ({len(items)} 只)')
            for code, name, added in items:
                print(f'     - {code} {name:<8} (加入: {added})')

    # 3. 按 tags 标签云
    tag_counter = Counter()
    for body in wl.values():
        for tag in (body.get('tags') or []):
            tag_counter[tag] += 1

    if tag_counter:
        print('\n\n## 按标签分布')
        print('-' * 70)
        for tag, count in tag_counter.most_common():
            print(f'  {tag:<12} × {count}')

    # 4. 按 added_at 时间线
    by_date = defaultdict(list)
    for code, body in wl.items():
        d = str(body.get('added_at', 'unknown'))
        by_date[d].append((code, body.get('name', ''), body.get('source', '')))

    print('\n\n## 加入时间线')
    print('-' * 70)
    for d in sorted(by_date.keys()):
        items = by_date[d]
        print(f'\n  📅 {d}  ({len(items)} 只)')
        for code, name, src in items:
            print(f'     - {code} {name:<8} ({src})')

    # 5. enabled 状态
    enabled_n = sum(1 for b in wl.values() if b.get('enabled', True))
    print(f'\n\n## 启用状态')
    print('-' * 70)
    print(f'  ✅ enabled: {enabled_n}  ❌ disabled: {len(wl) - enabled_n}')


if __name__ == '__main__':
    main()
