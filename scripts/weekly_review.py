"""
scripts/weekly_review.py — 周复盘
默认运行：上一周（周一-周五，含本周五如果是周五）
也可命令行指定：python weekly_review.py 2026-05-19  → 当周（含的周一计算）
推送：每周五 15:35 自动跑（PUSH=1）
"""
from __future__ import annotations
import os
import sys
import logging
import requests
from datetime import datetime, date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QUANT_DB_PATH', str(ROOT / 'data' / 'sim_live_mirror.db'))

from sim.review_lib import (
    get_conn, ACCOUNTS, aggregate_period, fmt_currency
)
from sim.config import load_config

logger = logging.getLogger('weekly-review')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

DB = Path(os.environ['QUANT_DB_PATH'])


def get_week_range(target_date: date) -> tuple[date, date]:
    """返回 target_date 所在周的 周一 ~ 周五"""
    monday = target_date - timedelta(days=target_date.weekday())
    friday = monday + timedelta(days=4)
    return monday, friday


def render_account(stat: dict, mon: date, fri: date) -> str:
    icon = '🤖' if stat['account_id'] == 1 else '💼'
    name_zh = '学习账户' if stat['account_id'] == 1 else '真实账户'
    lines = [f"## {icon} {name_zh}"]
    lines.append('')
    lines.append(f"💰 周末总值 ¥{stat['total_value']:,.2f}（现金 ¥{stat['cash']:,.2f}）")
    if stat['nav']:
        lines.append(f"📈 区间收益 {stat['period_return']:+.2f}% （{stat['start_value']:,.0f} → {stat['end_value']:,.0f}）")
    lines.append('')

    # 交易统计
    lines.append(f"### 📝 本周交易")
    lines.append(f"- 买入 {stat['buys_n']} 笔 / 卖出 {stat['sells_n']} 笔")
    if stat['realized']:
        emoji = '🟢' if stat['realized_total'] >= 0 else '🔴'
        lines.append(f"- 已平仓 {len(stat['realized'])} 笔 → 实现盈亏 {emoji} **{stat['realized_total']:+,.2f}**")
        lines.append(f"- 胜率 {stat['win_rate']:.0f}% ({stat['wins_n']}胜/{stat['losses_n']}负)")
        if stat['profit_factor'] > 0:
            lines.append(f"- 盈亏比 {stat['profit_factor']:.2f}")
    else:
        lines.append('- 本周无平仓')
    lines.append('')

    # 浮动盈亏
    if stat['positions']:
        emoji = '🟢' if stat['floating'] >= 0 else '🔴'
        lines.append(f"### 📦 周末持仓 {len(stat['positions'])} 只 (浮动 {emoji} {stat['floating']:+,.2f})")
        for p in stat['positions']:
            e = '🟢' if p['pnl'] >= 0 else '🔴'
            lines.append(
                f"- {e} **{p['stock_name']}** {p['quantity']}股 → "
                f"{p['pnl_pct']:+.2f}% ({p['pnl']:+.0f}) 市值 ¥{p['market_value']:,.0f}"
            )
        lines.append('')

    # 已平仓明细（前 5 条）
    if stat['realized']:
        lines.append('### 💵 平仓明细')
        for r in stat['realized'][:5]:
            e = '🟢' if r['pnl'] >= 0 else '🔴'
            lines.append(
                f"- {e} {r['date']} **{r['name']}** {r['qty']}股 "
                f"成本 ¥{r['avg_cost']:.2f} → 卖 ¥{r['sell_price']:.2f} = {r['pnl']:+.2f} ({r['pnl_pct']:+.2f}%)"
            )
        if len(stat['realized']) > 5:
            lines.append(f"... 还有 {len(stat['realized']) - 5} 笔")
        lines.append('')

    # nav 趋势
    if len(stat['nav']) >= 2:
        lines.append('### 📊 周内净值')
        for n in stat['nav']:
            lines.append(f"- {n['trade_date']} ¥{n['total_value']:,.2f} ({n['daily_return']:+.2f}%)")
        lines.append('')

    return '\n'.join(lines)


def render_summary(stats_by_account, mon: date, fri: date) -> str:
    """精简版给企微"""
    lines = [f"# 📅 周复盘 {mon} ~ {fri}\n"]
    for stat in stats_by_account:
        icon = '🤖' if stat['account_id'] == 1 else '💼'
        name_zh = '学习账户' if stat['account_id'] == 1 else '真实账户'
        lines.append(f"## {icon} {name_zh}")
        lines.append(
            f"💰 ¥{stat['total_value']:,.0f} "
            f"({stat['period_return']:+.2f}%)"
        )
        if stat['realized']:
            emoji = '🟢' if stat['realized_total'] >= 0 else '🔴'
            lines.append(
                f"📊 平仓 {len(stat['realized'])}笔 "
                f"实现 {emoji} **{stat['realized_total']:+,.2f}** "
                f"胜率 {stat['win_rate']:.0f}%"
            )
        lines.append(f"📦 周末持仓 {len(stat['positions'])}只 浮动 {stat['floating']:+,.2f}")
        lines.append('')
    return '\n'.join(lines)


def push_webhook(content):
    cfg = load_config()
    webhook = (cfg.get('notifier') or {}).get('wecom_webhook', '')
    if not webhook:
        logger.warning('webhook 未配置')
        return False
    try:
        resp = requests.post(webhook, json={
            'msgtype': 'markdown', 'markdown': {'content': content}
        }, timeout=8)
        ok = resp.json().get('errcode') == 0
        logger.info(f'推送 {"成功" if ok else "失败"}: {resp.text[:120]}')
        return ok
    except Exception as e:
        logger.error(f'异常: {e}')
        return False


def main():
    if len(sys.argv) > 1:
        target = date.fromisoformat(sys.argv[1])
    else:
        target = date.today()
    mon, fri = get_week_range(target)
    logger.info(f'=== 周复盘 {mon} ~ {fri} ===')

    conn = get_conn(DB)
    stats = []
    for acct in ACCOUNTS:
        s = aggregate_period(conn, acct['id'], mon, fri)
        stats.append(s)

    # 完整版
    parts = [f"# 📅 {mon.year}/{mon.month}/{mon.day} - {fri.month}/{fri.day} 周复盘\n"]
    for s in stats:
        parts.append(render_account(s, mon, fri))
        parts.append('---\n')
    parts.append(f"_生成时间: {datetime.now():%Y-%m-%d %H:%M:%S}_")
    full_md = '\n'.join(parts)

    out_dir = ROOT / 'output' / 'reviews_weekly'
    out_dir.mkdir(parents=True, exist_ok=True)
    md_file = out_dir / f"{mon.isoformat()}_to_{fri.isoformat()}.md"
    md_file.write_text(full_md, encoding='utf-8')
    logger.info(f'✓ 完整版: {md_file}')

    # 精简版
    summary = render_summary(stats, mon, fri)

    sum_file = out_dir / f"{mon.isoformat()}_summary.md"
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
