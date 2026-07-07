"""
REQ-067: 数据新鲜度监控脚本

检查各数据表的最后更新时间，如果超过阈值则输出告警。
由 cron 或 daily_review 调用。
"""
import sqlite3
from datetime import datetime, timedelta
import sys
import os

# 配置
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'sim_live_mirror.db')
STALE_THRESHOLD_HOURS = 24  # 超过24小时未更新视为stale
WARN_THRESHOLD_HOURS = 6    # 超过6小时未更新发出警告

def get_stale_seconds(updated_at_str):
    """计算数据距现在的秒数"""
    if not updated_at_str:
        return None
    try:
        updated = datetime.strptime(str(updated_at_str), '%Y-%m-%d %H:%M:%S')
        now = datetime.now()
        return (now - updated).total_seconds()
    except:
        return None

def check_data_freshness():
    conn = sqlite3.connect(DB_PATH)
    
    alerts = []
    warnings = []
    ok_items = []
    
    # 1. sim_account
    rows = conn.execute("SELECT id, account_name, updated_at FROM sim_account").fetchall()
    for r in rows:
        secs = get_stale_seconds(r[2])
        hours = secs / 3600 if secs else None
        item = f"sim_account[{r[0]}:{r[1]}]"
        if hours is None:
            alerts.append(f"⚠️ {item}: 无更新时间记录")
        elif hours > STALE_THRESHOLD_HOURS:
            alerts.append(f"🔴 {item}: 最后更新 {hours:.1f}h 前")
        elif hours > WARN_THRESHOLD_HOURS:
            warnings.append(f"🟡 {item}: 最后更新 {hours:.1f}h 前")
        else:
            ok_items.append(f"✅ {item}: {hours:.1f}h 前")
    
    # 2. sim_daily_nav 最新记录
    latest_nav = conn.execute("SELECT MAX(trade_date), MAX(created_at) FROM sim_daily_nav").fetchone()
    if latest_nav[0]:
        nav_date = datetime.strptime(latest_nav[0], '%Y-%m-%d')
        days_ago = (datetime.now() - nav_date).days
        if days_ago > 1:
            alerts.append(f"🔴 sim_daily_nav: 最新日期 {latest_nav[0]} ({days_ago}天前)")
        elif days_ago > 0:
            warnings.append(f"🟡 sim_daily_nav: 最新日期 {latest_nav[0]} ({days_ago}天前)")
        else:
            ok_items.append(f"✅ sim_daily_nav: 最新日期 {latest_nav[0]}")
    
    # 3. sim_trades 最新记录
    latest_trade = conn.execute("SELECT MAX(trade_date), MAX(created_at) FROM sim_trades").fetchone()
    if latest_trade[0]:
        trade_date = datetime.strptime(latest_trade[0], '%Y-%m-%d')
        days_ago = (datetime.now() - trade_date).days
        if days_ago > 3:
            warnings.append(f"🟡 sim_trades: 最新日期 {latest_trade[0]} ({days_ago}天前)")
        else:
            ok_items.append(f"✅ sim_trades: 最新日期 {latest_trade[0]}")
    
    # 4. threshold_state 检查积压
    armed_count = conn.execute("SELECT COUNT(*) FROM threshold_state WHERE status='armed'").fetchone()[0]
    if armed_count > 0:
        oldest = conn.execute("SELECT MIN(created_at) FROM threshold_state WHERE status='armed'").fetchone()[0]
        if oldest:
            old_date = datetime.strptime(oldest, '%Y-%m-%d %H:%M:%S')
            days = (datetime.now() - old_date).days
            if days > 1:
                alerts.append(f"🔴 threshold_state: {armed_count}条armed信号，最早{days}天前")
            else:
                warnings.append(f"🟡 threshold_state: {armed_count}条armed信号")
    
    conn.close()
    
    # 输出报告
    has_alert = len(alerts) > 0
    has_warn = len(warnings) > 0
    
    report_lines = ["## 📊 数据新鲜度检查", f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
    
    if alerts:
        report_lines.append("### 🔴 告警")
        report_lines.extend(alerts)
        report_lines.append("")
    
    if warnings:
        report_lines.append("### 🟡 警告")
        report_lines.extend(warnings)
        report_lines.append("")
    
    report_lines.append("### ✅ 正常")
    report_lines.extend(ok_items[:5])  # 最多显示5条正常项
    
    report = "\n".join(report_lines)
    print(report)
    
    return has_alert, has_warn, report


if __name__ == '__main__':
    has_alert, has_warn, report = check_data_freshness()
    
    # 如果是 cron 调用，可以通过 webhook 推送告警
    if has_alert and '--push' in sys.argv:
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
            from scripts.wecom_webhook import push_markdown
            push_markdown(report)
            print("\n📤 已推送告警到企微")
        except Exception as e:
            print(f"\n❌ 推送失败: {e}")
    
    sys.exit(1 if has_alert else 0)
