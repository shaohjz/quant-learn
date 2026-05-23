"""
scripts/monthly_review.py — 月复盘
默认运行：当前月（1号 ~ 今天）
也可命令行指定：python monthly_review.py 2026-05  → 整月
推送：每月最后一天 15:40 自动跑
"""
from __future__ import annotations
import os
import sys
import calendar
import logging
import requests
from datetime import datetime, date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QUANT_DB_PATH', str(ROOT / 'data' / 'sim_live_mirror.db'))

from sim.review_lib import get_conn, ACCOUNTS, aggregate_period
from sim.config import load_config

logger = logging.getLogger('monthly-review')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

DB = Path(os.environ['QUANT_DB_PATH'])


def get_month_range(target_date: date) -> tuple[date, date]:
    """返回 target_date 所在月的 1号 ~ 月末"""
    first = target_date.replace(day=1)
    last_day = calendar.monthrange(target_date.year, target_date.month)[1]
    last = target_date.replace(day=last_day)
    return first, last


def render_account(stat: dict, start: date, end: date) -> str:
    icon = '🤖' if stat['account_id'] == 1 else '💼'
    name_zh = '学习账户' if stat['account_id'] == 1 else '真实账户'
    lines = [f"## {icon} {name_zh}"]
    lines.append('')
    lines.append(f"💰 月末总值 ¥{stat['total_value']:,.2f}（现金 ¥{stat['cash']:,.2f}）")
    if stat['nav']:
        lines.append(f"📈 月度收益 {stat['period_return']:+.2f}% （{stat['start_value']:,.0f} → {stat['end_value']:,.0f}）")
    lines.append('')

    # 交易统计
    lines.append(f"### 📝 月度交易统计")
    lines.append(f"- 买入 {stat['buys_n']} 笔 / 卖出 {stat['sells_n']} 笔")
    if stat['realized']:
        emoji = '🟢' if stat['realized_total'] >= 0 else '🔴'
        lines.append(f"- 已平仓 {len(stat['realized'])} 笔 → 实现盈亏 {emoji} **{stat['realized_total']:+,.2f}**")
        lines.append(f"- 胜率 {stat['win_rate']:.0f}% ({stat['wins_n']}胜/{stat['losses_n']}负)")
        if stat['profit_factor'] > 0:
            lines.append(f"- 盈亏比 {stat['profit_factor']:.2f}")
    else:
        lines.append('- 本月无平仓')
    lines.append('')

    # 浮动持仓
    if stat['positions']:
        emoji = '🟢' if stat['floating'] >= 0 else '🔴'
        lines.append(f"### 📦 月末持仓 {len(stat['positions'])} 只 (浮动 {emoji} {stat['floating']:+,.2f})")
        for p in stat['positions']:
            e = '🟢' if p['pnl'] >= 0 else '🔴'
            lines.append(
                f"- {e} **{p['stock_name']}** {p['quantity']}股 → "
                f"{p['pnl_pct']:+.2f}% ({p['pnl']:+.0f})"
            )
        lines.append('')

    # 最佳/最差交易
    if stat['realized']:
        sorted_r = sorted(stat['realized'], key=lambda x: x['pnl'], reverse=True)
        lines.append('### 🏆 月度 TOP3 / 🩸 BOTTOM3')
        for r in sorted_r[:3]:
            e = '🟢'
            lines.append(
                f"- {e} {r['date']} {r['name']} {r['qty']}股 → {r['pnl']:+.2f} ({r['pnl_pct']:+.2f}%)"
            )
        if len(sorted_r) > 3:
            for r in sorted_r[-3:]:
                e = '🔴'
                lines.append(
                    f"- {e} {r['date']} {r['name']} {r['qty']}股 → {r['pnl']:+.2f} ({r['pnl_pct']:+.2f}%)"
                )
        lines.append('')

    # 月度 nav 简略（每周末）
    if len(stat['nav']) > 5:
        lines.append('### 📊 月度净值（每周末）')
        weekend_navs = [n for n in stat['nav'] 
                       if datetime.fromisoformat(n['trade_date']).weekday() == 4]  # 周五
        for n in weekend_navs:
            lines.append(f"- {n['trade_date']} ¥{n['total_value']:,.2f}")
        lines.append('')

    return '\n'.join(lines)


def render_summary(stats, start: date, end: date) -> str:
    lines = [f"# 📅 月复盘 {start.year}年{start.month}月\n"]
    for s in stats:
        icon = '🤖' if s['account_id'] == 1 else '💼'
        name_zh = '学习账户' if s['account_id'] == 1 else '真实账户'
        lines.append(f"## {icon} {name_zh}")
        lines.append(f"💰 ¥{s['total_value']:,.0f} ({s['period_return']:+.2f}%)")
        if s['realized']:
            emoji = '🟢' if s['realized_total'] >= 0 else '🔴'
            lines.append(
                f"📊 平仓 {len(s['realized'])}笔 实现 {emoji} **{s['realized_total']:+,.2f}** "
                f"胜率 {s['win_rate']:.0f}%"
            )
        lines.append(f"📦 月末持仓 {len(s['positions'])}只 浮动 {s['floating']:+,.2f}")
        lines.append('')
    return '\n'.join(lines)


def push_webhook(content):
    cfg = load_config()
    webhook = (cfg.get('notifier') or {}).get('wecom_webhook', '')
    if not webhook:
        return False
    try:
        resp = requests.post(webhook, json={'msgtype': 'markdown', 'markdown': {'content': content}}, timeout=8)
        return resp.json().get('errcode') == 0
    except Exception as e:
        logger.error(f'异常: {e}')
        return False


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if len(arg) == 7:  # YYYY-MM
            target = date.fromisoformat(arg + '-01')
        else:
            target = date.fromisoformat(arg)
    else:
        target = date.today()
    start, end = get_month_range(target)
    logger.info(f'=== 月复盘 {start} ~ {end} ===')

    conn = get_conn(DB)
    stats = []
    for acct in ACCOUNTS:
        s = aggregate_period(conn, acct['id'], start, end)
        stats.append(s)

    parts = [f"# 📅 {start.year}年{start.month}月 月度复盘 ({start.day}号 - {end.day}号)\n"]
    for s in stats:
        parts.append(render_account(s, start, end))
        parts.append('---\n')
    parts.append(f"_生成时间: {datetime.now():%Y-%m-%d %H:%M:%S}_")
    full_md = '\n'.join(parts)

    out_dir = ROOT / 'output' / 'reviews_monthly'
    out_dir.mkdir(parents=True, exist_ok=True)
    md_file = out_dir / f"{start.year}-{start.month:02d}.md"
    md_file.write_text(full_md, encoding='utf-8')
    logger.info(f'✓ 完整版: {md_file}')

    summary = render_summary(stats, start, end)
    sum_file = out_dir / f"{start.year}-{start.month:02d}_summary.md"
    sum_file.write_text(summary, encoding='utf-8')

    if os.environ.get('PUSH', '').lower() in ('1', 'true', 'yes'):
        push_webhook(summary)

    print('\n' + '=' * 70)
    try:
        print(summary)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((summary + '\n').encode('utf-8', errors='replace'))
    print('=' * 70)
    conn.close()


if __name__ == '__main__':
    main()
