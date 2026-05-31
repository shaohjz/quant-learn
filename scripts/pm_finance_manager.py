"""
scripts/pm_finance_manager.py — 职业理财经理 Agent（REQ-044）

每天收盘后（15:30）自动运行，从专业角度复盘当日操作，
分析仓位健康度，诊断策略表现，主动提出改进需求，推送日报到企微。

数据源：
  - data/sim_live_mirror.db  → sim_trades / sim_positions / sim_account / sim_daily_nav
  - data/real_holdings.json  → 实盘持仓（若存在）
  - docs/reviews/YYYY-MM-DD.md → 当日复盘报告
  - data/pm.db                → 当前 tasks 状态

输出：
  1. 理财经理日报（markdown）→ 推送企微
  2. 0~2 个新需求 → 直接写 pm.db
"""
from __future__ import annotations
import os
import sys
import json
import sqlite3
import subprocess
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.notify import send_markdown

logger = logging.getLogger('pm-finance-manager')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# ── 数据库路径 ────────────────────────────────────────────────────
SIM_DB = ROOT / 'data' / 'sim_live_mirror.db'
REAL_HOLDINGS = ROOT / 'data' / 'real_holdings.json'
PM_DB = ROOT / 'data' / 'pm.db'
REVIEWS_DIR = ROOT / 'docs' / 'reviews'

# ── 仓位健康度阈值 ───────────────────────────────────────────────
MAX_TOTAL_POSITION_PCT = 90   # 总仓位上限 %
MAX_SINGLE_POSITION_PCT = 15  # 单票仓位上限 %
MIN_CASH_PCT = 10              # 最低现金保留 %


def get_conn(db_path: Path = SIM_DB):
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    return c


def get_target_date():
    """从命令行参数获取日期，默认今天"""
    if len(sys.argv) > 1:
        return date.fromisoformat(sys.argv[1])
    return date.today()


# ═══════════════════════════════════════════════════════════════
# 1. 数据采集
# ═══════════════════════════════════════════════════════════════

def fetch_account(account_id: int = 1) -> dict | None:
    c = get_conn()
    r = c.execute('SELECT * FROM sim_account WHERE id=?', (account_id,)).fetchone()
    c.close()
    return dict(r) if r else None


def fetch_trades(account_id: int, target_date: date) -> list[dict]:
    c = get_conn()
    rows = c.execute(
        'SELECT * FROM sim_trades WHERE account_id=? AND trade_date=? ORDER BY id',
        (account_id, target_date.isoformat())
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def fetch_positions(account_id: int) -> list[dict]:
    c = get_conn()
    rows = c.execute(
        'SELECT * FROM sim_positions WHERE account_id=? ORDER BY market_value DESC',
        (account_id,)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def fetch_nav(account_id: int, target_date: date, days: int = 5) -> list[dict]:
    c = get_conn()
    rows = c.execute(
        '''SELECT * FROM sim_daily_nav 
           WHERE account_id=? AND trade_date <= ? 
           ORDER BY trade_date DESC LIMIT ?''',
        (account_id, target_date.isoformat(), days)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def fetch_real_holdings() -> list[dict]:
    """读取实盘持仓（real_holdings.json）"""
    if not REAL_HOLDINGS.exists():
        return []
    try:
        return json.loads(REAL_HOLDINGS.read_text(encoding='utf-8'))
    except Exception as e:
        logger.warning(f'读取 real_holdings.json 失败: {e}')
        return []


def fetch_review_content(target_date: date) -> str:
    """读取当日复盘报告内容"""
    review_file = REVIEWS_DIR / f'{target_date.isoformat()}.md'
    if review_file.exists():
        return review_file.read_text(encoding='utf-8')
    return ''


def count_recent_stop_loss(trades: list[dict], positions: list[dict]) -> list[str]:
    """统计最近连续止损 ≥ 2 次的股票（基于 sim_trades 历史）"""
    c = get_conn()
    # 取最近 10 天该账户的 SELL 交易
    cutoff = (datetime.now().date() - timedelta(days=10)).isoformat()
    rows = c.execute(
        '''SELECT stock_code, stock_name, trade_date, price, amount, signal_reason
           FROM sim_trades 
           WHERE account_id=1 AND direction="SELL" AND trade_date >= ?
           ORDER BY trade_date, id''',
        (cutoff,)
    ).fetchall()
    c.close()

    # 按股票统计卖出次数（假设 SELL 大概率是止损）
    code_count = defaultdict(int)
    code_names = {}
    for r in rows:
        code = r['stock_code']
        code_count[code] += 1
        code_names[code] = r['stock_name']

    # 筛选卖出 ≥ 2 次的
    return [f"{code_names[c]}({c})" for c, cnt in code_count.items() if cnt >= 2]


def fetch_pm_tasks() -> list[dict]:
    """读取当前 pm.db 中的 pending 任务"""
    c = sqlite3.connect(str(PM_DB))
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT id, type, title, priority, status FROM tasks WHERE status='pending' ORDER BY priority, id"
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════
# 2. 分析 + 评分
# ═══════════════════════════════════════════════════════════════

def compute_discipline_score(trades: list[dict], positions: list[dict], review_content: str) -> tuple[int, list[str]]:
    """
    纪律评分（⭐️ 1~5）：
      - 有止损执行：+1
      - 有止盈执行：+1
      - 没有追高（买入价不在当日最高 5% 内）：+1
      - 仓位未超限：+1
      - 现金保留 ≥ MIN_CASH_PCT%：+1
    返回 (score, reasons)
    """
    score = 5
    reasons = []

    # 检查是否有止损/止盈执行
    has_stop_loss = False
    has_take_profit = False
    for t in trades:
        reason = (t.get('signal_reason') or '').lower()
        if '止损' in reason or 'stop' in reason:
            has_stop_loss = True
        if '止盈' in reason or 'take profit' in reason:
            has_take_profit = True

    if not has_stop_loss and not has_take_profit:
        score -= 1
        reasons.append('当日无止损/止盈执行记录')

    # 检查是否追高（简化：如果有买入交易且 review 里提到"追高"则扣分）
    if '追高' in review_content:
        score -= 1
        reasons.append('复盘报告提到追高行为')

    # 检查仓位是否超限
    account = fetch_account(1)
    if account:
        total_assets = account['cash'] + sum(p.get('market_value', 0) for p in positions)
        if total_assets > 0:
            position_pct = (total_assets - account['cash']) / total_assets * 100
            if position_pct > MAX_TOTAL_POSITION_PCT:
                score -= 1
                reasons.append(f'总仓位 {position_pct:.1f}% 超过 {MAX_TOTAL_POSITION_PCT}%')

    # 检查现金保留
    if account and total_assets > 0 and 'total_assets' in dir():
        pass  # 上面已算
    # 重新算一次
    if account:
        total_assets = account['cash'] + sum(p.get('market_value', 0) for p in positions)
        cash_pct = account['cash'] / total_assets * 100 if total_assets > 0 else 100
        if cash_pct < MIN_CASH_PCT:
            score -= 1
            reasons.append(f'现金仅 {cash_pct:.1f}%，低于 {MIN_CASH_PCT}% 建议')

    score = max(1, min(5, score))
    return score, reasons


def analyze_positions(positions: list[dict], account: dict) -> dict:
    """分析仓位健康度"""
    if not account:
        return {'total_position_pct': 0, 'max_single_pct': 0, 'cash_pct': 100, 'warnings': []}

    total_assets = account['cash'] + sum(p.get('market_value', 0) for p in positions)
    if total_assets == 0:
        return {'total_position_pct': 0, 'max_single_pct': 0, 'cash_pct': 100, 'warnings': []}

    position_pct = (total_assets - account['cash']) / total_assets * 100
    cash_pct = account['cash'] / total_assets * 100

    max_single = 0
    max_single_name = ''
    for p in positions:
        single_pct = p.get('market_value', 0) / total_assets * 100
        if single_pct > max_single:
            max_single = single_pct
            max_single_name = p.get('stock_name', '')

    warnings = []
    if position_pct > MAX_TOTAL_POSITION_PCT:
        warnings.append(f'⚠️ 总仓位 {position_pct:.1f}% 超过建议上限 {MAX_TOTAL_POSITION_PCT}%')
    if max_single > MAX_SINGLE_POSITION_PCT:
        warnings.append(f'⚠️ {max_single_name} 占比 {max_single:.1f}%，超过单票上限 {MAX_SINGLE_POSITION_PCT}%')
    if cash_pct < MIN_CASH_PCT:
        warnings.append(f'⚠️ 现金仅 {cash_pct:.1f}%，低于建议下限 {MIN_CASH_PCT}%')

    return {
        'total_position_pct': position_pct,
        'max_single_pct': max_single,
        'max_single_name': max_single_name,
        'cash_pct': cash_pct,
        'cash': account['cash'],
        'total_assets': total_assets,
        'warnings': warnings,
    }


# ═══════════════════════════════════════════════════════════════
# 3. 生成日报
# ═══════════════════════════════════════════════════════════════

def generate_daily_report(target_date: date) -> str:
    """生成理财经理日报（Markdown）"""
    logger.info(f'生成理财经理日报 {target_date}...')

    # ── 数据采集 ──────────────────────────────────────────────────
    trades = fetch_trades(1, target_date)
    positions = fetch_positions(1)
    account = fetch_account(1)
    nav_history = fetch_nav(1, target_date, 5)
    real_holdings = fetch_real_holdings()
    review_content = fetch_review_content(target_date)
    stop_loss_stocks = count_recent_stop_loss(trades, positions)
    pm_tasks = fetch_pm_tasks()

    # ── 分析 ──────────────────────────────────────────────────────
    discipline_score, score_reasons = compute_discipline_score(trades, positions, review_content)
    position_analysis = analyze_positions(positions, account)

    buy_n = sum(1 for t in trades if t['direction'] == 'BUY')
    sell_n = len(trades) - buy_n
    today_pnl = sum((t.get('pnl') or 0) for t in trades if t['direction'] == 'SELL')

    # ── 组装日报 ──────────────────────────────────────────────────
    lines = []
    lines.append(f"📊 理财经理日报 · {target_date.year}/{target_date.month}/{target_date.day}")
    lines.append('')

    # 1. 今日操作复盘
    lines.append('### 📈 今日操作复盘')
    lines.append(f"- 模拟盘：买入 {buy_n} 笔 / 卖出 {sell_n} 笔")
    if account and nav_history:
        today_nav = nav_history[0] if nav_history else None
        if today_nav:
            lines.append(f"- 模拟盘当日收益：{today_nav['daily_return']:+.2f}%（累计 {today_nav.get('cumulative_return', 0):+.2f}%）")
    if real_holdings:
        lines.append(f"- 实盘持仓：{len(real_holdings)} 只")
    else:
        lines.append('- 实盘：无持仓数据')
    stars = '⭐️' * discipline_score + '☆' * (5 - discipline_score)
    lines.append(f'- 纪律评分：{stars} {discipline_score}/5')
    if score_reasons:
        for r in score_reasons:
            lines.append(f'  - {r}')
    lines.append('')

    # 2. 仓位分析
    lines.append('### 📊 仓位分析')
    lines.append(f"- 总仓位：{position_analysis['total_position_pct']:.1f}%（建议 ≤ {MAX_TOTAL_POSITION_PCT}%）")
    lines.append(f"- 最高单票：{position_analysis['max_single_name']} {position_analysis['max_single_pct']:.1f}%（建议 ≤ {MAX_SINGLE_POSITION_PCT}%）")
    lines.append(f"- 可用资金：¥{position_analysis['cash']:,.0f}（{position_analysis['cash_pct']:.1f}%，建议 ≥ {MIN_CASH_PCT}%）")
    if position_analysis['warnings']:
        lines.append('')
        for w in position_analysis['warnings']:
            lines.append(f'- {w}')
    lines.append('')

    # 3. 策略诊断
    lines.append('### 🔍 策略诊断')
    # 触发但未执行的信号（从 strategy_shadow_signals 查）
    c = get_conn()
    triggered = c.execute(
        '''SELECT COUNT(*) as cnt FROM strategy_shadow_signals 
           WHERE shadow_date=? AND signal_action IN ("BUY", "BUY_STRONG", "buy", "buy_strong")''',
        (target_date.isoformat(),)
    ).fetchone()
    executed_codes = set(t['stock_code'] for t in trades if t['direction'] == 'BUY')
    lines.append(f"- 今日触发买入信号：{triggered['cnt'] if triggered else '?'} 个")
    lines.append(f"- 实际执行买入：{buy_n} 笔")
    if stop_loss_stocks:
        lines.append(f"- 近期连续卖出 ≥ 2 次：{', '.join(stop_loss_stocks)}（建议重新评估）")
    else:
        lines.append('- 近期无连续止损股票 ✅')
    c.close()
    lines.append('')

    # 4. 改进建议（由 create_improvement_tasks 填写）
    lines.append('### 💡 改进建议')
    lines.append('（由 Agent 分析后自动建需求，见下方）')
    lines.append('')

    # 5. 明日重点关注
    lines.append('### 📌 明日重点关注')
    if positions:
        # 找浮亏最多的和浮盈最多的
        sorted_positions = sorted(positions, key=lambda p: p.get('pnl_pct', 0))
        if sorted_positions:
            worst = sorted_positions[0]
            best = sorted_positions[-1]
            lines.append(f"1. {worst['stock_name']}({worst['stock_code']}) 浮亏 {worst['pnl_pct']:.1f}%，关注是否触发止损")
            if best['pnl_pct'] > 10:
                lines.append(f"2. {best['stock_name']}({best['stock_code']}) 浮盈 {best['pnl_pct']:.1f}%，建议考虑 trailing stop")
    else:
        lines.append('1. 当前无持仓')
    lines.append('')

    lines.append(f"_生成时间: {datetime.now():%Y-%m-%d %H:%M:%S}_")
    lines.append('---')

    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════════════
# 4. 主动提出改进需求
# ═══════════════════════════════════════════════════════════════

def create_improvement_tasks(target_date: date, dry_run: bool = False) -> list[str]:
    """
    分析当前状态，自动提出 0~2 个改进需求。
    返回创建的 task id 列表。
    """
    created = []
    trades = fetch_trades(1, target_date)
    positions = fetch_positions(1)
    account = fetch_account(1)

    # 规则 1：执行率过低 → 建需求
    c = get_conn()
    triggered = c.execute(
        '''SELECT COUNT(*) as cnt FROM strategy_shadow_signals 
           WHERE shadow_date=? AND signal_action IN ("BUY", "BUY_STRONG", "buy", "buy_strong")''',
        (target_date.isoformat(),)
    ).fetchone()
    c.close()

    buy_n = sum(1 for t in trades if t['direction'] == 'BUY')
    triggered_cnt = triggered['cnt'] if triggered else 0
    exec_rate = buy_n / triggered_cnt * 100 if triggered_cnt > 0 else None

    if exec_rate is not None and exec_rate < 30 and triggered_cnt >= 3:
        title = f"提升买入信号执行率（当前 {exec_rate:.0f}%）"
        desc = (
            f"今日触发 {triggered_cnt} 个买入信号，执行 {buy_n} 笔，执行率 {exec_rate:.1f}%。\n"
            f"建议排查 sim_executor 的过滤条件是否过严（量比阈值、趋势过滤等）。"
        )
        task_id = _create_story(title, desc, priority='P1', dry_run=dry_run)
        if task_id:
            created.append(task_id)

    # 规则 2：现金过低 → 建需求
    if account:
        total_assets = account['cash'] + sum(p.get('market_value', 0) for p in positions)
        cash_pct = account['cash'] / total_assets * 100 if total_assets > 0 else 100
        if cash_pct < 5:
            title = f"现金过低预警（当前 {cash_pct:.1f}%）→ 优化仓位管理"
            desc = (
                f"当前现金仅 {cash_pct:.1f}%，可能影响后续买入执行。\n"
                f"建议：1) 设置单日最大建仓金额上限；2) 优先卖出浮亏超 8% 的仓位释放流动性。"
            )
            task_id = _create_story(title, desc, priority='P1', dry_run=dry_run)
            if task_id:
                created.append(task_id)

    # 规则 3：连续止损 → 建需求
    c = get_conn()
    cutoff = (target_date - timedelta(days=7)).isoformat()
    recent_sells = c.execute(
        '''SELECT stock_code, stock_name, COUNT(*) as cnt FROM sim_trades 
           WHERE account_id=1 AND direction="SELL" AND trade_date >= ?
           GROUP BY stock_code HAVING cnt >= 2''',
        (cutoff,)
    ).fetchall()
    c.close()
    if recent_sells and len(created) < 2:
        stocks_str = ', '.join(f"{r['stock_name']}({r['stock_code']})" for r in recent_sells[:3])
        title = f"连续止损诊断：{stocks_str}"
        desc = (
            f"近 7 日连续卖出 ≥ 2 次的股票：{stocks_str}。\n"
            f"建议：重新评估这些股票的量价特征，调整买入阈值或加入黑名单。"
        )
        task_id = _create_story(title, desc, priority='P2', dry_run=dry_run)
        if task_id:
            created.append(task_id)

    return created


def _create_story(title: str, desc: str, priority: str = 'P1', dry_run: bool = False) -> str | None:
    """调用 pm_cli.py create story，返回新任务的 id 或 None"""
    cmd = [
        sys.executable,
        str(ROOT / 'scripts' / 'pm_cli.py'),
        'create', 'story',
        title,
        '--desc', desc,
        '--priority', priority
    ]
    logger.info(f'创建需求: {title}')
    if dry_run:
        logger.info(f'[dry_run] {" ".join(cmd)}')
        return None

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=30)
        output = result.stdout.strip() or result.stderr.strip()
        logger.info(f'pm_cli 输出: {output}')
        # 从输出中提取 REQ-XXXX
        import re
        m = re.search(r'(REQ-\d+)', output)
        return m.group(1) if m else None
    except Exception as e:
        logger.error(f'创建需求失败: {e}')
        return None


# ═══════════════════════════════════════════════════════════════
# 5. 推送
# ═══════════════════════════════════════════════════════════════

def push_report(report: str) -> bool:
    """推送日报到企微"""
    try:
        result = send_markdown(report)
        if result and result.get('errcode') == 0:
            logger.info('✓ 日报推送成功')
            return True
        else:
            logger.error(f'推送失败: {result}')
            return False
    except Exception as e:
        logger.error(f'推送异常: {e}')
        return False


# ═══════════════════════════════════════════════════════════════
# 6. 主流程
# ═══════════════════════════════════════════════════════════════

def main():
    target_date = get_target_date()
    logger.info(f'=== 理财经理 Agent 启动 {target_date} ===')

    # 生成日报
    report = generate_daily_report(target_date)

    # 主动提出改进需求（最多 2 个）
    dry_run = os.environ.get('DRY_RUN', '').lower() in ('1', 'true', 'yes')
    created = create_improvement_tasks(target_date, dry_run=dry_run)

    # 把创建的需求补充到日报里
    if created:
        lines = report.split('\n')
        new_lines = []
        inserted = False
        for line in lines:
            new_lines.append(line)
            if not inserted and '（由 Agent 分析后自动建需求，见下方）' in line:
                for tid in created:
                    new_lines.append(f'- {tid}: 已自动创建（详见 pm.db）')
                inserted = True
        report = '\n'.join(new_lines)

    # 保存本地
    out_dir = ROOT / 'output' / 'finance_manager'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f'{target_date.isoformat()}.md'
    out_file.write_text(report, encoding='utf-8')
    logger.info(f'✓ 日报已保存: {out_file}')

    # 推送企微
    push_report(report)

    # 打印到 stdout（供 cron/runner 查看）
    print('\n' + '=' * 60)
    print(report)
    print('=' * 60)
    logger.info(f'=== 理财经理 Agent 完成 {target_date} ===')


if __name__ == '__main__':
    main()
