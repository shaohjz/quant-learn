"""
scripts/daily_review.py — 双账户日复盘 (rewrite 2026-05-22)

核心改进：
  1. 支持双账户：学习账户(id=1, live_mirror) + 真实账户(id=2, real_portfolio)分开复盘
  2. 显示 BUY/SELL 方向、价格、金额、手续费、信号理由
  3. 计算实现盈亏 (FIFO 平仓)
  4. 浮动盈亏从 sim_positions
  5. nav 历史从 sim_daily_nav，自动写入当日
  6. 推送精简版到企微 (markdown)
  7. 完整版本地保存 + 可选写 iwiki
"""
from __future__ import annotations
import os
import sys
import sqlite3
import logging
import requests
from datetime import datetime, date, timedelta
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QUANT_DB_PATH', str(ROOT / 'data' / 'sim_live_mirror.db'))

from sim.config import load_config

logger = logging.getLogger('daily-review')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

DB = Path(os.environ['QUANT_DB_PATH'])

ACCOUNTS = [
    {'id': 1, 'name': '学习账户', 'icon': '🤖', 'auto': True},
    {'id': 2, 'name': '真实账户', 'icon': '💼', 'auto': False},
]


# =====================================
# 1. 数据查询
# =====================================
def get_conn():
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    return c


def fetch_account(account_id: int):
    c = get_conn()
    r = c.execute('SELECT * FROM sim_account WHERE id=?', (account_id,)).fetchone()
    c.close()
    return dict(r) if r else None


def fetch_positions(account_id: int):
    c = get_conn()
    rows = c.execute(
        'SELECT * FROM sim_positions WHERE account_id=? ORDER BY market_value DESC',
        (account_id,)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def fetch_trades(account_id: int, target_date: date):
    c = get_conn()
    rows = c.execute(
        'SELECT * FROM sim_trades WHERE account_id=? AND trade_date=? ORDER BY id',
        (account_id, target_date.isoformat())
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def fetch_nav_history(account_id: int, target_date: date, n: int = 7):
    c = get_conn()
    rows = c.execute(
        '''SELECT * FROM sim_daily_nav 
           WHERE account_id=? AND trade_date <= ? 
           ORDER BY trade_date DESC LIMIT ?''',
        (account_id, target_date.isoformat(), n)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


# =====================================
# 2. 实现盈亏 (FIFO 配对)
# =====================================
def compute_realized_pnl(account_id: int, target_date: date):
    """FIFO 配对当日 SELL 与历史 BUY，算实现盈亏（卖出价 - 平均买入成本）* 数量 - 双向手续费"""
    c = get_conn()
    # 拉所有历史交易（截至当日）
    rows = c.execute(
        '''SELECT * FROM sim_trades WHERE account_id=? AND trade_date<=? ORDER BY trade_date, id''',
        (account_id, target_date.isoformat())
    ).fetchall()
    c.close()

    # 按股票代码分组，FIFO 队列
    queues = defaultdict(list)  # code -> [(qty, price, fee_per_share)]
    realized_today = []  # 当日卖出每笔实现 pnl

    for r in rows:
        code = r['stock_code']
        d = r['direction']
        qty = r['quantity']
        price = r['price']
        fee = (r['commission'] or 0) + (r['tax'] or 0)
        fee_per = fee / qty if qty else 0
        is_today = (r['trade_date'] == target_date.isoformat())

        if d == 'BUY':
            queues[code].append([qty, price, fee_per])
        elif d == 'SELL':
            remaining = qty
            cost_total = 0.0
            buy_fee_total = 0.0
            while remaining > 0 and queues[code]:
                head = queues[code][0]
                take = min(head[0], remaining)
                cost_total += take * head[1]
                buy_fee_total += take * head[2]
                head[0] -= take
                remaining -= take
                if head[0] == 0:
                    queues[code].pop(0)

            if is_today:
                consumed = qty - remaining
                if consumed > 0:
                    sell_amount = consumed * price
                    sell_fee = fee * (consumed / qty)
                    pnl = sell_amount - cost_total - buy_fee_total - sell_fee
                    pnl_pct = (price / (cost_total / consumed) - 1) * 100 if cost_total > 0 else 0
                    try:
                        sr = r['signal_reason'] or ''
                    except (IndexError, KeyError):
                        sr = ''
                    realized_today.append({
                        'code': code,
                        'name': r['stock_name'],
                        'qty': consumed,
                        'sell_price': price,
                        'avg_cost': cost_total / consumed if consumed > 0 else 0,
                        'pnl': pnl,
                        'pnl_pct': pnl_pct,
                        'signal_reason': sr,
                    })

    return realized_today


# =====================================
# 3. nav 写入 + 计算
# =====================================
def write_daily_nav(account_id: int, target_date: date, account: dict, positions: list, initial_cash: float | None = None):
    market_value = sum(p['market_value'] for p in positions)
    total_value = market_value + account['cash']
    # 优先用传入的 initial_cash，否则从 account dict 取
    if initial_cash is None:
        initial_cash = account.get('initial_cash') or 100000.0
    initial = initial_cash
    cumulative_return = (total_value / initial - 1) * 100

    c = get_conn()
    last = c.execute(
        '''SELECT total_value FROM sim_daily_nav 
           WHERE account_id=? AND trade_date < ? 
           ORDER BY trade_date DESC LIMIT 1''',
        (account_id, target_date.isoformat())
    ).fetchone()
    prev_value = last['total_value'] if last else initial
    daily_return = (total_value / prev_value - 1) * 100 if prev_value > 0 else 0

    # 最大回撤
    all_navs = c.execute(
        'SELECT total_value FROM sim_daily_nav WHERE account_id=? ORDER BY trade_date',
        (account_id,)
    ).fetchall()
    peak = initial
    for r in all_navs:
        peak = max(peak, r['total_value'])
    peak = max(peak, total_value)
    max_drawdown = (total_value / peak - 1) * 100

    c.execute(
        '''INSERT OR REPLACE INTO sim_daily_nav 
           (account_id, trade_date, total_value, cash, market_value, daily_return, cumulative_return, max_drawdown)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (account_id, target_date.isoformat(), total_value, account['cash'], market_value,
         daily_return, cumulative_return, max_drawdown)
    )
    c.commit()
    c.close()

    return {
        'total_value': total_value,
        'cash': account['cash'],
        'market_value': market_value,
        'daily_return': daily_return,
        'cumulative_return': cumulative_return,
        'max_drawdown': max_drawdown,
        'prev_value': prev_value,
    }


# =====================================
# 4. 文本生成
# =====================================
def render_account_section(acct: dict, target_date: date) -> str:
    lines = []
    
    # ── REQ-035: 资金口径一致性检测 ──────────────────────
    try:
        from sim.db import detect_cash_discrepancy
        discrepancy = detect_cash_discrepancy(acct['id'])
    except Exception:
        discrepancy = None
    # ──────────────────────────────────────────────────────────

    account = fetch_account(acct['id'])
    # REQ-035: 用 config.yaml 的 initial_cash（而非数据库旧值）计算 nav
    try:
        from sim.config import get_account_config
        cfg = get_account_config(acct['id'])
        config_initial = cfg['initial_cash']
    except Exception:
        config_initial = (account or {}).get('initial_cash', 100000.0)

    if not account:
        # 即使没有账户记录，也要输出口径警告（如果有）
        if discrepancy:
            lines.append(f"## {acct['icon']} {acct['name']}")
            lines.append('')
            lines.append('⚠️ **资金口径异常**：数据库无账户记录，但 config.yaml 中有配置')
            lines.append('')
        return '\n'.join(lines)

    positions = fetch_positions(acct['id'])
    trades = fetch_trades(acct['id'], target_date)
    realized = compute_realized_pnl(acct['id'], target_date)
    nav = write_daily_nav(acct['id'], target_date, account, positions, initial_cash=config_initial)

    realized_pnl = sum(r['pnl'] for r in realized)
    floating_pnl = sum(p['pnl'] for p in positions)

    # 标题行（如有口径问题，加警告图标）
    title_prefix = '⚠️ ' if discrepancy else ''
    lines.append(f"## {title_prefix}{acct['icon']} {acct['name']}")
    lines.append('')

    # 口径不一致警告（放在最显眼的位置）
    if discrepancy:
        icon = '⚠️' if discrepancy['severity'] == 'warn' else '🚨'
        lines.append(
            f"{icon} **资金口径不一致！** "
            f"config ¥{discrepancy['config_initial_cash']:,.0f} "
            f"vs DB ¥{discrepancy['db_initial_cash']:,.0f} "
            f"（差¥{discrepancy['diff']:+,.0f} / {discrepancy['diff_pct']*100:+.1f}%）"
        )
        lines.append('> PnL 计算以 **config.yaml** 为准，数据库值未同步。')
        lines.append('> 修复：`from sim.db import sync_account_initial_cash; sync_account_initial_cash('
                    + str(acct['id']) + ', source="config")`')
        lines.append('')

    lines = []
    lines.append(f"## {acct['icon']} {acct['name']}")
    lines.append('')
    lines.append(
        f"💰 总资产 ¥{nav['total_value']:,.2f} "
        f"(现金 ¥{nav['cash']:,.2f} + 持仓市值 ¥{nav['market_value']:,.2f})"
    )
    lines.append(
        f"📈 当日 {nav['daily_return']:+.2f}% | "
        f"累计 {nav['cumulative_return']:+.2f}% | "
        f"回撤 {nav['max_drawdown']:+.2f}%"
    )
    lines.append('')

    # 当日交易
    if trades:
        lines.append(f"### 📝 当日交易 {len(trades)} 笔")
        for t in trades:
            arrow = '🟢 买' if t['direction'] == 'BUY' else '🔴 卖'
            amt = t.get('amount') or (t['price'] * t['quantity'])
            fee = (t.get('commission') or 0) + (t.get('tax') or 0)
            reason = t.get('signal_reason') or ''
            line = (
                f"- {arrow} **{t['stock_name']}** ({t['stock_code']}) "
                f"{t['quantity']}股 @¥{t['price']:.2f} = ¥{amt:,.2f} "
                f"(手续费 ¥{fee:.2f})"
            )
            if reason:
                line += f"  _{reason}_提供"
            lines.append(line)
            # REQ-032: 展开 signal_detail
            _detail_raw = t.get('signal_detail') or ''
            if _detail_raw and isinstance(_detail_raw, str) and len(_detail_raw) > 10:
                import json as _json
                try:
                    _detail = _json.loads(_detail_raw)
                    _triggered = _detail.get('triggered_rules', [])
                    _snap = _detail.get('indicators_snapshot', {})
                    _ver = _detail.get('strategy_version', '')
                    _lines = [f"  策略版本: {_ver}"] if _ver else []
                    if _triggered:
                        _lines.append("  触发规则:")
                        for _r in _triggered:
                            _cur = _r.get('current_value')
                            _th = _r.get('threshold')
                            _op = _r.get('operator', '?')
                            _val = f"{_cur:.4f}" if isinstance(_cur, (int, float)) else str(_cur)
                            _thr = f"{_th:.4f}" if isinstance(_th, (int, float)) else str(_th)
                            _lines.append(f"    - {_r.get('rule', '')}: 当前值 {_val} {_op} 阈值 {_thr}")
                    if _snap:
                        _lines.append("  指标快照: " + ', '.join(
                            f"{k}={v}" for k, v in _snap.items() if v is not None
                        )[:200])
                    _summary = ' | '.join(
                        _r.get('rule', '')[:20] for _r in (_triggered or [])[:3]
                    )
                    lines.append('<details>')
                    lines.append(f'<summary>📋 查看完整信号解释（{_summary or "触发详情"}）</summary>')
                    for _l in _lines:
                        lines.append(_l)
                    lines.append('</details>')
                except Exception:
                    pass
            elif _detail_raw and isinstance(_detail_raw, dict):
                # 已经是 dict（测试场景）
                _triggered = _detail_raw.get('triggered_rules', [])
                _summary = ' | '.join(
                    _r.get('rule', '')[:20] for _r in (_triggered or [])[:3]
                )
                lines.append('<details>')
                lines.append(f'<summary>📋 查看完整信号解释（{_summary or "触发详情"}）</summary>')
                for _r in (_triggered or [])[:5]:
                    _cur = _r.get('current_value')
                    _th = _r.get('threshold')
                    _op = _r.get('operator', '?')
                    _val = f"{_cur:.4f}" if isinstance(_cur, (int, float)) else str(_cur)
                    _thr = f"{_th:.4f}" if isinstance(_th, (int, float)) else str(_th)
                    lines.append(f"  - {_r.get('rule', '')}: 当前值 {_val} {_op} 阈值 {_thr}")
                lines.append('</details>')
        lines.append('')

        if realized:
            lines.append(f"### 💵 当日实现盈亏（FIFO 配对）")
            for r in realized:
                emoji = '🟢' if r['pnl'] >= 0 else '🔴'
                lines.append(
                    f"- {emoji} **{r['name']}** ({r['code']}) {r['qty']}股 "
                    f"成本 ¥{r['avg_cost']:.3f} → 卖 ¥{r['sell_price']:.2f} "
                    f"= {r['pnl']:+.2f} ({r['pnl_pct']:+.2f}%)"
                )
            lines.append(f"\n**🎯 当日实现盈亏合计: {realized_pnl:+,.2f}**")
            lines.append('')
    else:
        lines.append('_当日无交易_')
        lines.append('')

    # 当前持仓 + 浮动盈亏
    if positions:
        lines.append(f"### 📦 当前持仓 {len(positions)} 只")
        for p in positions:
            emoji = '🟢' if p['pnl'] >= 0 else '🔴'
            lines.append(
                f"- {emoji} **{p['stock_name']}** ({p['stock_code']}) "
                f"{p['quantity']}股 成本 ¥{p['avg_cost']:.3f} → 现 ¥{p['current_price']:.2f} "
                f"= {p['pnl']:+.2f} ({p['pnl_pct']:+.2f}%) 市值 ¥{p['market_value']:,.0f}"
            )
        lines.append(f"\n**浮动盈亏合计: {floating_pnl:+,.2f}**")
    else:
        lines.append('_当前空仓_')

    lines.append('')

    # nav 趋势（最近 5 天）
    history = fetch_nav_history(acct['id'], target_date, 5)
    if len(history) >= 2:
        lines.append('### 📊 近 5 日总资产')
        for h in reversed(history):
            lines.append(
                f"- {h['trade_date']}: ¥{h['total_value']:,.2f} ({h['daily_return']:+.2f}%)"
            )
        lines.append('')

    return '\n'.join(lines)


def generate_full_md(target_date: date) -> str:
    parts = [f"# 📊 {target_date.year}/{target_date.month}/{target_date.day} 日复盘\n"]
    for acct in ACCOUNTS:
        parts.append(render_account_section(acct, target_date))
        parts.append('---\n')
    parts.append(f"_生成时间: {datetime.now():%Y-%m-%d %H:%M:%S}_\n")
    return '\n'.join(parts)


def generate_wecom_summary(target_date: date) -> str:
    """精简版给企微（只放真实账户 + 学习账户的当日核心数据）"""
    lines = [f"# 📊 {target_date.year}/{target_date.month}/{target_date.day} 日复盘\n"]

    for acct in ACCOUNTS:
        account = fetch_account(acct['id'])
        if not account:
            continue
        positions = fetch_positions(acct['id'])
        trades = fetch_trades(acct['id'], target_date)
        realized = compute_realized_pnl(acct['id'], target_date)
        nav_history = fetch_nav_history(acct['id'], target_date, 1)
        nav = nav_history[0] if nav_history else None

        lines.append(f"## {acct['icon']} {acct['name']}")
        if nav:
            lines.append(
                f"💰 ¥{nav['total_value']:,.0f} "
                f"({nav['daily_return']:+.2f}% / 累计 {nav['cumulative_return']:+.2f}%)"
            )

        if trades:
            buy_n = sum(1 for t in trades if t['direction'] == 'BUY')
            sell_n = len(trades) - buy_n
            realized_pnl = sum(r['pnl'] for r in realized)
            lines.append(f"📝 交易 {len(trades)} 笔（买 {buy_n} / 卖 {sell_n}）")
            for t in trades[:5]:
                arrow = '🟢' if t['direction'] == 'BUY' else '🔴'
                action = '买' if t['direction'] == 'BUY' else '卖'
                lines.append(
                    f"- {arrow} {action} {t['stock_name']} {t['quantity']}股 @¥{t['price']:.2f}"
                )
            if realized:
                emoji = '🎉' if realized_pnl >= 0 else '😢'
                lines.append(f"💵 实现盈亏 **{realized_pnl:+,.2f}** {emoji}")
        else:
            lines.append('_当日无交易_')

        if positions:
            float_pnl = sum(p['pnl'] for p in positions)
            lines.append(f"📦 持仓 {len(positions)} 只 浮动 {float_pnl:+,.2f}")
            for p in positions[:3]:
                emoji = '🟢' if p['pnl'] >= 0 else '🔴'
                lines.append(
                    f"  {emoji} {p['stock_name']} {p['quantity']}股 → "
                    f"{p['pnl_pct']:+.2f}% ({p['pnl']:+.0f})"
                )

        lines.append('')

    return '\n'.join(lines)


# =====================================
# 5. 推送
# =====================================
def push_webhook(content: str) -> bool:
    cfg = load_config()
    webhook = (cfg.get('notifier') or {}).get('wecom_webhook', '')
    if not webhook:
        logger.warning('未配置 wecom_webhook，跳过推送')
        return False
    try:
        resp = requests.post(webhook, json={
            'msgtype': 'markdown',
            'markdown': {'content': content}
        }, timeout=8)
        ok = resp.json().get('errcode') == 0
        logger.info(f'推送 {"成功" if ok else "失败"}: {resp.text[:120]}')
        return ok
    except Exception as e:
        logger.error(f'推送异常: {e}')
        return False


# =====================================
# 6. 主流程
# =====================================
def get_target_date() -> date:
    """命令行 arg 或 今日"""
    if len(sys.argv) > 1:
        return date.fromisoformat(sys.argv[1])
    return date.today()


def main():
    target_date = get_target_date()
    logger.info(f'=== 开始复盘 {target_date} ===')

    full_md = generate_full_md(target_date)
    out_dir = ROOT / 'output' / 'reviews'
    out_dir.mkdir(parents=True, exist_ok=True)
    md_file = out_dir / f"{target_date.isoformat()}.md"
    md_file.write_text(full_md, encoding='utf-8')
    logger.info(f'✓ 完整版已存: {md_file}')

    summary = generate_wecom_summary(target_date)
    sum_file = out_dir / f"{target_date.isoformat()}_summary.md"
    sum_file.write_text(summary, encoding='utf-8')
    logger.info(f'✓ 精简版已存: {sum_file}')

    # 仅在 push=1 / push=true 时推送（默认不推，需要时显式）
    push_flag = os.environ.get('PUSH', '').lower() in ('1', 'true', 'yes')
    if push_flag:
        push_webhook(summary)
    else:
        logger.info('未推送（设 PUSH=1 启用），可执行 `python scripts/daily_review.py %s` 重跑' % target_date)

    print('\n' + '=' * 70)
    try:
        print(summary)
    except UnicodeEncodeError:
        # Windows GBK 控制台处理不了 emoji，转 ascii 安全输出
        sys.stdout.buffer.write((summary + '\n').encode('utf-8', errors='replace'))
    print('=' * 70)


if __name__ == '__main__':
    main()
