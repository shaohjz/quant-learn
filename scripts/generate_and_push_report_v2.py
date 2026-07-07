#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成并推送每日复盘报告 v2"""

import sqlite3
from datetime import datetime
import subprocess
import os

def generate_enhanced_report():
    """生成增强版日报，包含问题分析和建议"""
    
    conn = sqlite3.connect('data/sim_live_mirror.db')
    cursor = conn.cursor()
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    report = f"# 📊 {today} 理财师每日复盘报告\n\n"
    
    # 1. 账户概况
    report += "## 💰 账户概况\n\n"
    
    cursor.execute("""
        SELECT account_name, cash, total_value, updated_at 
        FROM sim_account 
        ORDER BY id
    """)
    accounts = cursor.fetchall()
    
    issues_found = []
    
    for acc in accounts:
        acc_name, cash, total_value, updated_at = acc
        report += f"**{acc_name}账户**\n"
        report += f"- 💵 现金: ¥{cash:,.2f}\n"
        report += f"- 📈 总市值: ¥{total_value:,.2f}\n"
        
        if acc_name == 'learn':
            initial = 200000.0
            account_type = "模拟学习账户"
        else:
            initial = 25000.0
            account_type = "实盘模拟账户"
        
        pnl = total_value - initial
        pnl_pct = (pnl / initial) * 100
        emoji = "📉" if pnl < 0 else "📈"
        report += f"- {emoji} 累计收益: ¥{pnl:,.2f} ({pnl_pct:+.2f}%)\n"
        report += f"- 📅 更新时间: {updated_at}\n\n"
        
        # 检查问题
        if pnl_pct < -20:
            issues_found.append({
                'type': 'critical',
                'title': f'{acc_name}账户巨额亏损',
                'desc': f'账户亏损{pnl_pct:.1f}%，远超可接受范围',
                'priority': 'high'
            })
    
    # 2. 今日交易分析
    report += "## 🔄 今日交易分析\n\n"
    
    cursor.execute("""
        SELECT stock_code, stock_name, direction, 
               price, quantity, signal_reason, trade_time
        FROM sim_trades
        WHERE trade_date = ?
        ORDER BY trade_time
    """, (today,))
    trades = cursor.fetchall()
    
    if not trades:
        report += "今日无交易记录\n\n"
    else:
        # 分析交易问题
        trade_dict = {}
        for trade in trades:
            code, name, direction, price, qty, reason, time = trade
            
            if code not in trade_dict:
                trade_dict[code] = {'buy': [], 'sell': []}
            
            trade_dict[code][direction.lower()].append({
                'time': time,
                'price': price,
                'qty': qty,
                'reason': reason
            })
        
        # 检查同一股票同日买卖
        same_day_trades = []
        for code, trade_info in trade_dict.items():
            if trade_info['buy'] and trade_info['sell']:
                same_day_trades.append(code)
                buy_time = trade_info['buy'][0]['time']
                sell_time = trade_info['sell'][0]['time']
                
                report += f"⚠️ **{code} 同日双向交易**\n"
                report += f"  - 买入: {buy_time} @ ¥{trade_info['buy'][0]['price']:.2f}\n"
                report += f"  - 卖出: {sell_time} @ ¥{trade_info['sell'][0]['price']:.2f}\n"
                
                issues_found.append({
                    'type': 'strategy',
                    'title': f'{code}策略冲突 - 同日双向交易',
                    'desc': f'同一日在{buy_time}买入，在{sell_time}卖出，可能存在策略信号冲突',
                    'priority': 'medium'
                })
        
        # 列出所有交易
        report += "\n### 交易明细\n\n"
        for trade in trades:
            code, name, direction, price, qty, reason, time = trade
            
            direction_emoji = "🟢" if direction == "BUY" else "🔴"
            report += f"{direction_emoji} **{time} {direction} {code} {name}**\n"
            report += f"  - 价格: ¥{price:.2f} | 数量: {qty}股\n"
            report += f"  - 信号: {reason}\n\n"
    
    # 3. 策略执行分析
    report += "## 🤖 策略执行分析\n\n"
    
    cursor.execute("""
        SELECT COUNT(*) 
        FROM strategy_shadow_signals 
        WHERE shadow_date = ? 
        AND signal_action = 'BUY'
    """, (today,))
    buy_signals = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) 
        FROM strategy_shadow_signals 
        WHERE shadow_date = ? 
        AND signal_action = 'SELL'
    """, (today,))
    sell_signals = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) 
        FROM review_decisions 
        WHERE trade_date = ? 
        AND allowed = 0
    """, (today,))
    blocked_trades = cursor.fetchone()[0]
    
    report += f"- 📊 今日买入信号: {buy_signals}个\n"
    report += f"- 📊 今日卖出信号: {sell_signals}个\n"
    report += f"- 🚫 被拦截交易: {blocked_trades}笔\n\n"
    
    if blocked_trades > 20:
        issues_found.append({
            'type': 'system',
            'title': '风控拦截过多',
            'desc': f'今日被拦截{blocked_trades}笔交易，可能是风控规则过于严格',
            'priority': 'medium'
        })
    
    # 4. 发现的问题汇总
    if issues_found:
        report += "## ⚠️ 发现的问题\n\n"
        
        for i, issue in enumerate(issues_found, 1):
            priority_emoji = "🔴" if issue['priority'] == 'high' else "🟡"
            report += f"{i}. {priority_emoji} **{issue['title']}**\n"
            report += f"   - {issue['desc']}\n\n"
    
    # 5. 建议
    report += "## 💡 建议与改进\n\n"
    
    if any(i['priority'] == 'high' for i in issues_found):
        report += "### 🔴 紧急处理\n\n"
        report += "1. **learn账户巨额亏损调查**\n"
        report += "   - 查看历史交易记录，找出亏损原因\n"
        report += "   - 检查是否有异常交易或系统错误\n"
        report += "   - 考虑重置账户或调整策略参数\n\n"
    
    report += "### 🟡 优化建议\n\n"
    report += "1. **优化交易策略**\n"
    report += "   - 解决同一股票同日双向交易问题\n"
    report += "   - 检查买卖信号逻辑是否有冲突\n"
    report += "   - 增加信号确认机制，避免频繁交易\n\n"
    
    report += "2. **调整风控规则**\n"
    report += "   - 评估当前拦截规则是否合理\n"
    report += "   - 如果被拦截交易过多，考虑放宽限制\n"
    report += "   - 添加更细粒度的风控规则\n\n"
    
    report += "3. **增强监控**\n"
    report += "   - 添加实时盈亏监控告警\n"
    report += "   - 设置单日最大亏损限制\n"
    report += "   - 定期检查持仓集中度\n\n"
    
    report += "---\n"
    report += "*本报告由理财师AI自动生成 @ " + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + "*\n"
    
    conn.close()
    
    return report, issues_found

def add_tasks_to_pm_db(issues):
    """向PM数据库添加任务"""
    
    if not issues:
        print("✅ 未发现需要记录的问题")
        return
    
    conn = sqlite3.connect('data/pm.db')
    cursor = conn.cursor()
    
    # 确保tasks表存在
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        type TEXT,
        title TEXT NOT NULL,
        description TEXT,
        status TEXT DEFAULT 'pending',
        priority TEXT DEFAULT 'medium',
        created_at TEXT,
        updated_at TEXT,
        assigned_to TEXT,
        result_notes TEXT,
        root_cause TEXT,
        fix_commit TEXT,
        work_notes TEXT
    )
    ''')
    
    added_count = 0
    for issue in issues:
        task_id = f"TASK-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{added_count+1:03d}"
        
        try:
            cursor.execute('''
            INSERT INTO tasks (
                id, type, title, description, status, priority, 
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task_id,
                issue['type'],
                issue['title'],
                issue['desc'],
                'pending',
                issue['priority'],
                datetime.now().isoformat(),
                datetime.now().isoformat()
            ))
            added_count += 1
            print(f"✅ 已添加任务: {task_id} - {issue['title']}")
        except Exception as e:
            print(f"❌ 添加任务失败: {e}")
    
    conn.commit()
    conn.close()
    print(f"\n共添加 {added_count} 个任务到PM数据库")

def push_report_to_wecom(report):
    """推送报告到企微群"""
    
    try:
        # 将报告写入临时文件
        temp_file = 'temp_report.md'
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"\n📤 正在推送日报到企微群...")
        
        # 使用wecom_webhook推送
        cmd = [
            'python', '-c', 
            f'import sys; sys.path.insert(0, r"C:\\Users\\Administrator\\.openclaw\\workspace\\quant-learn"); '
            f'from scripts.wecom_webhook import push_markdown; '
            f'push_markdown(open(r"{os.path.abspath(temp_file)}", "r", encoding="utf-8").read())'
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True, 
            text=True,
            cwd='C:/Users/Administrator/.openclaw/workspace/quant-learn',
            timeout=30
        )
        
        if result.returncode == 0:
            print("✅ 成功推送日报到企微群")
            return True
        else:
            print(f"❌ 推送失败: {result.stderr}")
            print(f"stdout: {result.stdout}")
            return False
            
    except Exception as e:
        print(f"❌ 推送异常: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # 清理临时文件
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except:
            pass

if __name__ == '__main__':
    print("="*60)
    print("理财师每日复盘 - 开始执行")
    print("="*60 + "\n")
    
    print("📊 正在生成每日复盘报告...")
    report, issues = generate_enhanced_report()
    
    print("\n" + "="*60)
    print("报告预览:")
    print("="*60)
    print(report[:500] + "..." if len(report) > 500 else report)
    print("="*60 + "\n")
    
    # 添加任务到PM数据库
    print("📝 正在向PM数据库添加任务...")
    add_tasks_to_pm_db(issues)
    
    # 推送到企微群
    print("\n" + "="*60)
    push_report_to_wecom(report)
    print("="*60)
    
    print("\n✅ 理财师每日复盘完成!")
