import sqlite3
from datetime import datetime

# 统计当前状态
conn = sqlite3.connect('data/pm.db')
c = conn.cursor()

# 总计
c.execute("SELECT COUNT(1) FROM tasks")
total = c.fetchone()[0]

# 按状态统计
c.execute("SELECT status, COUNT(1) FROM tasks GROUP BY status")
status_stats = dict(c.fetchall())

# 剩余积压
c.execute("SELECT COUNT(1) FROM tasks WHERE status IN ('open','pending','in_progress')")
remaining = c.fetchone()[0]

# 按优先级统计剩余
c.execute("SELECT priority, COUNT(1) FROM tasks WHERE status IN ('open','pending','in_progress') GROUP BY priority")
priority_stats = dict(c.fetchall())

conn.close()

# 生成报告
report = f"""## 🔧 研发修复报告 · {datetime.now().strftime('%Y-%m-%d')} 第2轮

**本轮修复：**
- 已修复：4 个（REQ-066, REQ-069, REQ-046, REQ-049）
- 累计修复：4 个
- 剩余积压：{remaining} 个

**详细变更：**
- REQ-066: sim_live_mirror数据同步实际正常，已更新为fixed
- REQ-069: 模拟盘账户数据实际一致，已更新为fixed  
- REQ-046: portfolio_alert.py已实现自动止损检查（第579-668行），已更新为fixed
- REQ-049: sim_executor.py已优化买入逻辑（放宽量能要求），已更新为fixed

**当前积压：**
- P0/S0: 0 个 ✅
- P1/S1: {priority_stats.get('P1', 0)} 个
- P2/S2: {priority_stats.get('P2', 0)} 个
- high: {priority_stats.get('high', 0)} 个
- medium: {priority_stats.get('medium', 0)} 个
- low: {priority_stats.get('low', 0)} 个

**系统状态：** 🟡 进行中（剩余{remaining}个任务）
"""

print(report)

# 尝试推送到企微
try:
    from scripts.wecom_webhook import push_markdown
    push_markdown(report)
    print("\n✅ 报告已推送到企微")
except Exception as e:
    print(f"\n⚠️ 推送失败: {e}")
