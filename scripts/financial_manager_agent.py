"""
scripts/financial_manager_agent.py — 职业理财经理 Agent

每天收盘后（15:30）自动运行：
1. 读取今日所有成交记录 + 持仓现状
2. 从专业角度复盘：仓位管理是否合理、买卖策略是否执行到位
3. 主动提出改进需求（直接写 pm.db）
4. 推送一份简洁的「理财经理日报」到企微群

运行方式:
  - 定时: 每个交易日 15:30（通过 cron 或 scheduler 触发）
  - 手动: python scripts/financial_manager_agent.py
"""

from __future__ import annotations
import os
import sys
import sqlite3
import logging
import subprocess
from datetime import datetime, date, timedelta
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logger = logging.getLogger('financial-manager')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# 数据库路径
SIM_DB = ROOT / 'data' / 'sim_live_mirror.db'
PM_DB = ROOT / 'data' / 'pm.db'
REVIEWS_DIR = ROOT / 'docs' / 'reviews'

# 账户配置
ACCOUNTS = [
    {'id': 1, 'name': '学习账户', 'icon': '🤖'},
    {'id': 2, 'name': '真实账户', 'icon': '💼'},
]

def get_conn(db_path: Path):
    """获取数据库连接"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn

def read_today_trades(account_id: int, target_date: date):
    """读取指定账户今日的成交记录"""
    conn = get_conn(SIM_DB)
    rows = conn.execute(
        'SELECT * FROM sim_trades WHERE account_id=? AND trade_date=? ORDER BY id',
        (account_id, target_date.isoformat())
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def read_positions(account_id: int):
    """读取指定账户的持仓"""
    conn = get_conn(SIM_DB)
    rows = conn.execute(
        'SELECT * FROM sim_positions WHERE account_id=? ORDER BY market_value DESC',
        (account_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def read_account_info(account_id: int):
    """读取账户信息"""
    conn = get_conn(SIM_DB)
    row = conn.execute('SELECT * FROM sim_account WHERE id=?', (account_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def read_daily_nav(account_id: int, target_date: date, days: int = 7):
    """读取近期 NAV 历史"""
    conn = get_conn(SIM_DB)
    rows = conn.execute(
        '''SELECT * FROM sim_daily_nav 
           WHERE account_id=? AND trade_date <= ? 
           ORDER BY trade_date DESC LIMIT ?''',
        (account_id, target_date.isoformat(), days)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def calculate_discipline_score(trades, positions):
    """计算纪律评分（0-5星）"""
    score = 5  # 满分开始扣
    
    # 检查是否有止损执行
    stop_loss_count = 0
    for trade in trades:
        if 'STOP' in trade.get('signal', '').upper() or '止损' in trade.get('reason', ''):
            stop_loss_count += 1
    
    # 如果有止损信号但未执行，扣分
    if stop_loss_count == 0 and len(positions) > 0:
        # 检查持仓中是否有亏损超过5%的
        for pos in positions:
            if pos.get('unrealized_pnl', 0) < -0.05 * pos.get('market_value', 0):
                score -= 1
                break
    
    # 检查仓位集中度
    total_value = sum(p.get('market_value', 0) for p in positions)
    if total_value > 0:
        max_position_ratio = max(p.get('market_value', 0) for p in positions) / total_value
        if max_position_ratio > 0.15:  # 单票占比超过15%
            score -= 1
    
    # 检查现金比例
    account = read_account_info(1)  # 默认检查学习账户
    if account:
        cash_ratio = account.get('cash', 0) / (account.get('cash', 0) + total_value)
        if cash_ratio < 0.1:  # 现金低于10%
            score -= 1
    
    return max(1, score)  # 最低1星

def analyze_strategy_performance(trades):
    """分析策略表现，找出连续失败的信号"""
    strategy_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'recent': []})
    
    for trade in trades:
        signal = trade.get('signal', 'UNKNOWN')
        pnl = trade.get('realized_pnl', 0)
        
        if pnl > 0:
            strategy_stats[signal]['wins'] += 1
        else:
            strategy_stats[signal]['losses'] += 1
        
        strategy_stats[signal]['recent'].append(pnl)
        
        # 只保留最近5次
        if len(strategy_stats[signal]['recent']) > 5:
            strategy_stats[signal]['recent'] = strategy_stats[signal]['recent'][-5:]
    
    # 找出近期胜率下降的策略
    weak_strategies = []
    for signal, stats in strategy_stats.items():
        recent = stats['recent']
        if len(recent) >= 3:
            recent_wins = sum(1 for p in recent if p > 0)
            win_rate = recent_wins / len(recent)
            if win_rate < 0.4:  # 胜率低于40%
                weak_strategies.append((signal, win_rate, len(recent)))
    
    return weak_strategies

def generate_improvement_suggestions(trades, positions, account_info):
    """生成改进建议，并自动创建任务"""
    suggestions = []
    
    # 1. 检查是否有连续止损
    recent_trades = [t for t in trades if t.get('trade_date') == date.today().isoformat()]
    stop_loss_trades = [t for t in recent_trades if 'STOP' in t.get('signal', '').upper()]
    
    if len(stop_loss_trades) >= 2:
        suggestions.append({
            'title': f'连续止损 {len(stop_loss_trades)} 次，需要重新评估参数',
            'desc': f'今日连续止损股票：{", ".join([t.get("symbol") for t in stop_loss_trades])}',
            'priority': 'P1'
        })
    
    # 2. 检查仓位集中度
    total_value = sum(p.get('market_value', 0) for p in positions)
    if total_value > 0:
        max_position = max(positions, key=lambda p: p.get('market_value', 0))
        max_ratio = max_position.get('market_value', 0) / total_value
        
        if max_ratio > 0.15:
            suggestions.append({
                'title': f'单票仓位过高：{max_position.get("symbol")} 占比 {max_ratio:.1%}',
                'desc': '建议单票仓位不超过15%，降低集中度风险',
                'priority': 'P1'
            })
    
    # 3. 检查现金比例
    if account_info:
        cash = account_info.get('cash', 0)
        total_assets = cash + total_value
        cash_ratio = cash / total_assets if total_assets > 0 else 0
        
        if cash_ratio < 0.1:
            suggestions.append({
                'title': f'现金比例过低：{cash_ratio:.1%}',
                'desc': '建议保留至少10%现金应对突发机会',
                'priority': 'P2'
            })
    
    return suggestions

def create_task_in_pm(task_data):
    """在 pm.db 中创建新任务"""
    try:
        # 使用 pm_cli.py 创建任务
        cmd = [
            str(ROOT / '.venv' / 'Scripts' / 'python.exe'),
            str(ROOT / 'scripts' / 'pm_cli.py'),
            'create',
            'story',
            task_data['title'],
            '--desc', task_data['desc'],
            '--priority', task_data['priority'],
            '--status', 'pending'
        ]
        
        result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        
        if result.returncode == 0:
            logger.info(f"Created task: {task_data['title']}")
            return True
        else:
            logger.error(f"Failed to create task: {result.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        return False

def generate_daily_report(target_date: date):
    """生成每日理财经理报告"""
    report = f"📊 理财经理日报 · {target_date.isoformat()}\n\n"
    
    for account in ACCOUNTS:
        account_id = account['id']
        icon = account['icon']
        name = account['name']
        
        report += f"### {icon} {name} 今日操作复盘\n"
        
        # 读取数据
        trades = read_today_trades(account_id, target_date)
        positions = read_positions(account_id)
        account_info = read_account_info(account_id)
        
        # 统计交易
        buy_count = sum(1 for t in trades if t.get('direction') == 'BUY')
        sell_count = sum(1 for t in trades if t.get('direction') == 'SELL')
        
        report += f"- 模拟盘：买入 {buy_count} 笔 / 卖出 {sell_count} 笔\n"
        
        # 纪律评分
        discipline_score = calculate_discipline_score(trades, positions)
        report += f"- 纪律评分：{'⭐️' * discipline_score}/{discipline_score}/5\n"
        
        # 仓位分析
        total_value = sum(p.get('market_value', 0) for p in positions)
        report += f"\n### 📊 仓位分析\n"
        report += f"- 总仓位：{total_value:,.2f} 元\n"
        
        if account_info:
            cash = account_info.get('cash', 0)
            total_assets = cash + total_value
            cash_ratio = cash / total_assets if total_assets > 0 else 0
            report += f"- 可用资金：¥{cash:,.2f} ({cash_ratio:.1%})\n"
        
        # 策略诊断
        weak_strategies = analyze_strategy_performance(trades)
        if weak_strategies:
            report += f"\n### 🔍 策略诊断\n"
            report += f"- 近期胜率下降的策略：\n"
            for signal, win_rate, count in weak_strategies:
                report += f"  - {signal}: 近{count}次胜率 {win_rate:.0%}\n"
        
        report += "\n"
    
    # 改进建议
    suggestions = generate_improvement_suggestions(
        read_today_trades(1, target_date),  # 默认使用学习账户
        read_positions(1),
        read_account_info(1)
    )
    
    if suggestions:
        report += "### 💡 改进建议（已自动建需求）\n"
        for i, sug in enumerate(suggestions, 1):
            report += f"{i}. {sug['title']}（优先级 {sug['priority']}）\n"
            # 自动创建任务
            create_task_in_pm(sug)
        report += "\n"
    
    # 明日重点关注
    report += "### 📊 明日重点关注\n"
    positions = read_positions(1)
    for pos in positions[:3]:  # 只显示前3个持仓
        symbol = pos.get('symbol')
        unrealized_pnl = pos.get('unrealized_pnl', 0)
        cost = pos.get('cost', 0)
        
        if unrealized_pnl < -0.05 * cost:  # 亏损超过5%
            report += f"1. {symbol} 接近止损线，明天盯紧\n"
        elif unrealized_pnl > 0.2 * cost:  # 盈利超过20%
            report += f"2. {symbol} 浮盈 {unrealized_pnl/cost:.1%}，建议启动 trailing stop\n"
    
    return report

def send_report_to_wecom(report_content: str):
    """发送报告到企微群"""
    try:
        # 使用 notify.py 发送
        notify_script = ROOT / 'scripts' / 'notify.py'
        
        # 写入临时文件
        temp_file = ROOT / 'output' / 'financial_manager_report.md'
        temp_file.write_text(report_content, encoding='utf-8')
        
        # 调用 notify.py
        cmd = [
            str(ROOT / '.venv' / 'Scripts' / 'python.exe'),
            str(notify_script),
            'markdown',
            '--stdin'
        ]
        
        with open(temp_file, 'r', encoding='utf-8') as f:
            result = subprocess.run(cmd, cwd=str(ROOT), stdin=f, capture_output=True, text=True)
        
        if result.returncode == 0:
            logger.info("Report sent to WeCom successfully")
            return True
        else:
            logger.error(f"Failed to send report: {result.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending report: {e}")
        return False

def main():
    """主函数"""
    target_date = date.today()
    
    logger.info(f"Starting financial manager agent for {target_date}")
    
    # 生成报告
    report = generate_daily_report(target_date)
    
    # 保存到本地
    report_file = REVIEWS_DIR / f"{target_date.isoformat()}_financial_manager.md"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(report, encoding='utf-8')
    logger.info(f"Report saved to {report_file}")
    
    # 发送到企微
    send_report_to_wecom(report)
    
    logger.info("Financial manager agent completed")

if __name__ == '__main__':
    main()
