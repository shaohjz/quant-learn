"""
vqlearn/services/signal_review.py — 策略信号复盘 + 事后跟踪

功能：
1. 当日触发概览：threshold_state 每个状态的数量
2. 当日已成交：sim_trades 里 broker='live_mirror' 且 trade_date=today
3. 信号事后跟踪：对历史每条 buy/sell 信号，看 1/3/5 日后股价变化（赚没赚）
4. 量过滤拦截统计：从 vqlearn_live.log 解析

输出：返回 dict，由 daily_review 拼到报告里
"""
from __future__ import annotations

import os
import sys
import re
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault('QUANT_DB_PATH', str(ROOT / 'data' / 'sim_live_mirror.db'))

from sim.db import get_conn


# ============================================================
#  1. 当日触发概览
# ============================================================
def get_today_signals(target_date: str) -> dict:
    """返回 target_date 当日 threshold_state 触发概览"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM threshold_state
           WHERE first_hit_date=? OR last_check_date=?
           ORDER BY id""",
        (target_date, target_date)
    ).fetchall()
    conn.close()

    by_status = {'pending': [], 'armed': [], 'confirmed': [], 'expired': [], 'executed': []}
    for r in rows:
        d = dict(r)
        s = d.get('status', 'unknown')
        if s in by_status:
            by_status[s].append(d)
    return by_status


def get_today_executed_trades(target_date: str) -> list[dict]:
    """获取 target_date 当日 vqlearn 触发的真成交（broker='live_mirror'）"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM sim_trades
           WHERE trade_date=? AND broker='live_mirror'
           ORDER BY id""",
        (target_date,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
#  2. 信号事后跟踪
# ============================================================
def track_signal_outcomes(days_after: list[int] = [1, 3, 5]) -> list[dict]:
    """
    遍历所有 threshold_state（status='executed' 且有 first_hit_price 的），
    用 akshare 拉历史数据，看信号触发 N 日后股价变化。

    Returns:
        list of dict: 每条信号一个字典，含 1日/3日/5日 涨跌幅
    """
    import akshare as ak

    conn = get_conn()
    rows = conn.execute(
        """SELECT stock_code, stock_name, rule_name, rule_threshold,
                  first_hit_date, first_hit_price, notes
           FROM threshold_state
           WHERE status='executed' AND first_hit_price > 0
           ORDER BY first_hit_date DESC LIMIT 50"""
    ).fetchall()
    conn.close()

    today = date.today()
    out = []
    for r in rows:
        d = dict(r)
        signal_date = d['first_hit_date']
        try:
            sd = datetime.strptime(signal_date, '%Y-%m-%d').date()
        except Exception:
            continue
        signal_price = d['first_hit_price']
        code = d['stock_code']

        # 拉信号日 +max(days_after) 天的 K 线
        max_d = max(days_after)
        end = (sd + timedelta(days=max_d * 2 + 5)).strftime('%Y%m%d')
        start = sd.strftime('%Y%m%d')

        prefix = 'sh' if code.startswith(('60', '68', '11', '12', '5')) else (
                 'sz' if code.startswith(('00', '30', '15', '16')) else 'sh')
        sina_code = prefix + code

        try:
            df = ak.stock_zh_a_daily(symbol=sina_code, start_date=start, end_date=end, adjust='qfq')
            if df is None or len(df) == 0:
                continue
            # 找信号当日及之后的收盘
            df['date'] = df['date'].astype(str)
            df_after = df[df['date'] >= signal_date].reset_index(drop=True)
            if len(df_after) == 0:
                continue

            row = {
                'code': code,
                'name': d['stock_name'],
                'rule': d['rule_name'],
                'signal_date': signal_date,
                'signal_price': signal_price,
                'is_anomaly': 'DATA_ANOMALY' in (d.get('notes') or ''),
            }
            for nd in days_after:
                if len(df_after) > nd:
                    after_close = float(df_after.iloc[nd]['close'])
                    chg = (after_close - signal_price) / signal_price * 100
                    row[f'{nd}d_close'] = after_close
                    row[f'{nd}d_pct'] = chg
                else:
                    # 还没到 N 天，用最新一行
                    if (today - sd).days < nd:
                        row[f'{nd}d_close'] = None
                        row[f'{nd}d_pct'] = None
                    else:
                        # 数据不足，跳过
                        row[f'{nd}d_close'] = None
                        row[f'{nd}d_pct'] = None
            out.append(row)
        except Exception as e:
            logger.debug(f'track {code} 失败: {e}')
            continue

    return out


# ============================================================
#  3. 量过滤拦截统计（解析日志）
# ============================================================
def count_volume_blocks_today(target_date: str) -> dict:
    """从 vqlearn_live.log + vqlearn_live.prev.log 解析量过滤拦截"""
    log_files = [
        ROOT / 'output' / 'vqlearn_live.log',
        ROOT / 'output' / 'vqlearn_live.prev.log',
    ]
    pattern_block = re.compile(r'⚠️ \[(buy_zone|buy_strong)\] (\d+\.\w+) ([\d.]+).*量不足|开盘<5min')
    pattern_pass = re.compile(r'(🟢|🟢🟢) \[(buy_zone|buy_strong)\] (\d+\.\w+) ([\d.]+) ≤ ')

    blocks = []
    passes = []
    target_prefix = target_date  # like '2026-05-21'

    for lf in log_files:
        if not lf.exists():
            continue
        try:
            for line in lf.read_text(encoding='utf-8', errors='replace').splitlines():
                if target_prefix not in line:
                    continue
                if pattern_block.search(line):
                    blocks.append(line.strip())
                elif pattern_pass.search(line):
                    passes.append(line.strip())
        except Exception as e:
            logger.debug(f'读 {lf} 失败: {e}')

    return {
        'blocked_count': len(blocks),
        'passed_count': len(passes),
        'blocked_samples': blocks[:5],
        'passed_samples': passes[:5],
    }


# ============================================================
#  4. 综合输出（给 daily_review.py 调用）
# ============================================================
def build_signal_review_section(target_date: str) -> str:
    """生成 markdown 形式的策略信号复盘 section"""
    parts = []
    parts.append("## 🤖 vqlearn 策略信号复盘\n")

    # ---- 当日触发概览 ----
    sig = get_today_signals(target_date)
    parts.append(f"### 📍 当日阈值触发\n")
    parts.append(f"- 🟡 pending（盘中触发，等收盘确认）: **{len(sig['pending'])}**")
    parts.append(f"- 🔵 armed（收盘确认，等次日开盘确认）: **{len(sig['armed'])}**")
    parts.append(f"- ✅ executed（已下单成交）: **{len(sig['executed'])}**")
    parts.append(f"- ♻️ expired（假摔/未确认）: **{len(sig['expired'])}**\n")

    if sig['pending']:
        parts.append("**Pending 详情：**")
        parts.append("| 股票 | 规则 | 阈值 | 触发价 | 备注 |")
        parts.append("| --- | --- | --- | --- | --- |")
        for s in sig['pending']:
            parts.append(f"| {s['stock_code']} {s['stock_name']} | {s['rule_name']} | {s['rule_threshold']:.2f} | {s.get('first_hit_price', 0):.2f} | {s.get('notes', '')[:30]} |")
        parts.append("")

    if sig['armed']:
        parts.append("**⚠️ Armed 待次日确认：**")
        parts.append("| 股票 | 规则 | 阈值 | 收盘价 | 备注 |")
        parts.append("| --- | --- | --- | --- | --- |")
        for s in sig['armed']:
            parts.append(f"| {s['stock_code']} {s['stock_name']} | {s['rule_name']} | {s['rule_threshold']:.2f} | {s.get('close_price', 0):.2f} | 明日 9:35-9:40 自动确认 |")
        parts.append("")

    if sig['executed']:
        parts.append("**✅ 当日已执行：**")
        parts.append("| 股票 | 规则 | 阈值 | 成交价 | 备注 |")
        parts.append("| --- | --- | --- | --- | --- |")
        for s in sig['executed']:
            parts.append(f"| {s['stock_code']} {s['stock_name']} | {s['rule_name']} | {s['rule_threshold']:.2f} | {s.get('first_hit_price', 0):.2f} | {s.get('notes', '')[:30]} |")
        parts.append("")

    if sig['expired']:
        parts.append("**♻️ 已失效（假摔/未确认）：**")
        parts.append("| 股票 | 规则 | 阈值 | 备注 |")
        parts.append("| --- | --- | --- | --- |")
        for s in sig['expired'][:5]:
            parts.append(f"| {s['stock_code']} {s['stock_name']} | {s['rule_name']} | {s['rule_threshold']:.2f} | {s.get('notes', '')[:30]} |")
        parts.append("")

    # ---- 量过滤拦截 ----
    vol = count_volume_blocks_today(target_date)
    parts.append(f"### 🚦 量过滤效果\n")
    parts.append(f"- 通过: **{vol['passed_count']}** 条")
    parts.append(f"- 拦截: **{vol['blocked_count']}** 条（成交量不足）")
    if vol['blocked_samples']:
        parts.append("\n拦截样本：")
        for s in vol['blocked_samples'][:3]:
            parts.append(f"- `{s[-150:]}`")
    parts.append("")

    # ---- 信号事后跟踪 ----
    outcomes = track_signal_outcomes(days_after=[1, 3, 5])
    if outcomes:
        parts.append(f"### 📈 历史信号事后回报跟踪\n")
        parts.append("| 信号日 | 股票 | 规则 | 触发价 | T+1 收盘 | T+1 % | T+3 % | T+5 % | 标签 |")
        parts.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for o in outcomes[:20]:
            t1 = f"{o['1d_pct']:+.2f}%" if o.get('1d_pct') is not None else '—'
            t3 = f"{o['3d_pct']:+.2f}%" if o.get('3d_pct') is not None else '—'
            t5 = f"{o['5d_pct']:+.2f}%" if o.get('5d_pct') is not None else '—'
            t1c = f"{o['1d_close']:.2f}" if o.get('1d_close') else '—'
            tag = '⚠️ 数据异常' if o.get('is_anomaly') else ''
            parts.append(f"| {o['signal_date']} | {o['code']} {o['name']} | {o['rule']} | {o['signal_price']:.2f} | {t1c} | {t1} | {t3} | {t5} | {tag} |")
        parts.append("")

        # 简单胜率统计（排除异常信号）
        for nd in [1, 3, 5]:
            valid = [o for o in outcomes if o.get(f'{nd}d_pct') is not None and not o.get('is_anomaly')]
            if not valid:
                continue
            # 对买入信号：上涨即胜；对卖出信号：下跌即胜
            wins = 0
            for o in valid:
                pct = o[f'{nd}d_pct']
                if o['rule'] in ('buy_zone', 'buy_strong') and pct > 0:
                    wins += 1
                elif o['rule'] in ('trend_break', 'take_profit', 'take_profit_half') and pct < 0:
                    wins += 1
            total = len(valid)
            win_rate = wins / total * 100 if total > 0 else 0
            avg_pct = sum(o[f'{nd}d_pct'] for o in valid) / total if total > 0 else 0
            parts.append(f"- **T+{nd} 胜率**: {wins}/{total} = {win_rate:.0f}% | 平均涨跌: {avg_pct:+.2f}%")

    return "\n".join(parts)


if __name__ == '__main__':
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    print(build_signal_review_section(target))
