# 研发经理每日汇报 — 2026-06-13（周六）

---

## 一、项目整体进展

| 指标 | 数值 |
|------|------|
| PM任务总数 | 85（61个Story + 24个Bug） |
| 已完成(done+verified+deployed) | 51个（60.0%） |
| 进行中(in_progress) | 14个 |
| 待测试(testing) | 8个 |
| 待处理(open+todo) | 7个 |
| 代码文件数 | 577 files changed (+119,738 / -7,095) |
| 最近提交 | fcc1a22 (6/11 部署日志), 66890b4 (6/11 部署), bbcb988 (6/11 release) |

## 二、最近2天已完成开发项（6/10-6/11 部署周期）

| 任务 | 说明 | 状态 |
|------|------|------|
| REQ-042 量化通知去大模型化 | 纯代码+企微Webhook直推，更新Windows计划任务 | ✅ deployed |
| BUG-20260610-001 AKShare连接失败修复 | 数据源替换/fallback增强 | ✅ deployed |
| BUG-20260610-002 xtquant导入失败修复 | 可选导入+module检查 | ✅ deployed |
| notify脚本 wecom_webhook导入修复 | sys.path加入scripts目录 | ✅ deployed |

## 三、进行中开发项

| 任务 | 优先级 | 最后更新 | 说明 |
|------|--------|----------|------|
| **BUG-019** sim_live_mirror.db 数据过期/写入链路中断 | P0 | 6/9 | 持仓数据停在6/2，逾期7天 |
| **REQ-059** 持仓追踪止损价格未全覆盖 | P1 | 6/9 | 6只持仓无止损保护 |
| REQ-013 系统/策略级别异常监控与告警 | P2 | 6/2 | 已实现HealthMonitor基础框架 |
| REQ-058 SELL成交signal_reason为空 | P? | 6/2 | 卖出操作无法溯源信号 |
| REQ-011 vnpy OmsEngine详细订单回放 | P1 | 6/2 | 测试失败已回到in_progress |
| REQ-043 量化通知cron去大模型化 | P? | 6/1 | agentTurn→systemEvent改造 |
| REQ-049 买入信号执行率5%→提升 | P? | 6/1 | 19触发→1执行 |
| REQ-046 持仓止损自动触发 | P? | 5/28 | 严重浮亏自动卖出 |
| REQ-051 同一股票同日多信号去重 | P? | 5/28 | 避免重复买入 |
| 其他5个REQ | P1-P2 | 5/28-6/2 | REQ-026/019/045/036/001 |

## 四、待处理新Bug（6/10复盘发现，均open状态）

| Bug | 优先级 | 问题描述 |
|-----|--------|----------|
| **REQ-060** | P1 | 西部材料(002149)建仓信号MA20=67.7但成交价59.6，偏离-11.9%，阈值计算错误 |
| **REQ-061** | P1 | sim_daily_nav中account_id=1的daily_return持续为NULL，收益率无法计算 |
| **REQ-063** | P1 | 豫能控股(001896) take_profit armed后8天才卖出，且以止损价成交而非止盈价 |
| **REQ-064** | P1 | account_id=2价格stale（停在5/22），trailing_stop和盈亏显示错误 |
| REQ-062 | P2 | daily_buy_budget_guard冷静期30分钟+预算计算需评审 |

## 五、🔴 本次发现的架构问题

**严重Bug：Web应用DB路径错误导致仪表盘数据缺失**

- **根因**：`web/app.py` 第18行 `DB_PATH = ROOT / "data" / "sim_live_mirror.db"`，但该DB只有 `review_reflections` 表（2行记录），**缺少全部持仓/交易/资产表**。
- **正确的数据位置**：真实数据在 `data/sim.db`，包含完整的 `sim_account`、`sim_positions`、`sim_trades`、`sim_daily_nav`、`sim_orders`、`sim_fills` 等表。
- **影响**：Web仪表盘 `/api/portfolio`、`/api/equity_curve`、`/api/trades` 等核心API无法返回真实持仓数据，用户看到的界面是空的。
- **修复方案**：将第18行改为 `DB_PATH = ROOT / "data" / "sim.db"`，或配置为统一的数据库路径。

**重复需求**：REQ-065和REQ-066是完全相同的重复需求（都描述了 sim_live_mirror.db 缺少表的问题），应合并为一个。

## 六、模拟盘数据现状

| DB | 表数 | 数据量 |
|----|------|--------|
| `data/sim_live_mirror.db` | 2 | review_reflections: 2行（仅复盘反思） |
| `data/sim.db` | 8 | sim_account:1 row, sim_positions:1行, 其他基本为空 |

**数据严重不足**：`sim.db` 中只有1条持仓记录、0条交易记录、0条净值记录，这意味着核心量化引擎的数据写入链路已断裂。

## 七、建议行动

1. **🔴 紧急**：修复 `web/app.py` DB路径 → 改为 `sim.db`
2. **🔴 紧急**：恢复量化引擎数据写入链路（vnpy runner/sim_executor）
3. **🟡 重要**：合并 REQ-065/REQ-066 重复需求
4. **🟡 重要**：处理 REQ-060~REQ-064 四个新的P1级Bug
5. **🟢 一般**：推进14个 in_progress 需求的验收和关闭
6. **🟢 一般**：对8个 testing 状态的需求进行回归测试

## 八、子研发Agent使用情况

当前未使用子研发agent。如需并行推进上述Bug修复和新功能开发，建议分配：
- **Agent-1**：修复DB路径 + 数据写入链路恢复
- **Agent-2**：修复REQ-060（MA阈值计算错误）
- **Agent-3**：修复REQ-061（daily_return NULL）
- **Agent-4**：修复REQ-063（止盈/止损策略执行偏差）
- **Agent-5**：修复REQ-064（account_id=2价格更新）

---

*生成时间：2026-06-13 20:02 CST | 研发经理 automated report*
