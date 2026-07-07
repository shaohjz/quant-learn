"""
生成本轮修复报告并推送到企微
"""
import sys
sys.path.insert(0, '.')
from scripts.wecom_webhook import push_markdown

report = """## 🔧 量化系统修复报告 2026-07-06 21:00

### ✅ 已修复 (6项)

**🔴 P0**
- <font color="info">REQ-093</font> NAV异常跳变（+35.4%）— 修正7/3 sim_daily_nav数据，total从228,917→164,768，daily_return从+35.4%→-2.5%
- <font color="info">TASK-0215-003</font> 7/3 NAV异常核查 — 根因：config_sync将initial_cash误写为100K，修复NAV曲线

**🟡 P1**
- <font color="info">REQ-095</font> sim_daily_nav 7/3后停止写入 — 7/6的NAV已恢复正常写入
- <font color="info">REQ-072</font> real_portfolio无NAV记录 — 已写入account_id=2初始NAV记录（6/2和7/6）
- <font color="info">REQ-067</font> 数据新鲜度监控 — 新增 `scripts/check_data_freshness.py`，覆盖账户/NAV/交易/信号检查
- <font color="info">REQ-068</font> threshold_state积压监控 — 积压信号已清理，监控已集成到freshness脚本
- <font color="info">REQ-065</font> 累计收益率异常(-78.12%) — initial_cash已从43K修正为200K，cum_return现为+10.9%

### ⏸️ 未修复 (4项，需信号引擎级改动)

- <font color="warning">TASK-0215-004</font> 建投能源连续3日买入即止损 — 同一K线穿透buy_strong→trend_break，需信号引擎仲裁逻辑
- <font color="warning">TASK-2006-002</font> 工业富联买入滑点 — 需买入前价格复验+滑点保护
- <font color="info">REQ-092</font> 买入前估值分析(PE/PB过滤) — 大feature，需单独开发窗口
- <font color="info">REQ-062</font> 冷静期评审 — 需代码级改动引入同股票冷却独立逻辑

### 📊 数据健康
- sim_daily_nav 最新: 2026-07-06 ✅
- sim_account.learn 最后更新: 8.9h前 🟡
- threshold_state armed: 0条 ✅"""

push_markdown(report)
print("报告已推送")
