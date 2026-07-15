# CRON_JOBS.md — 量化模拟盘定时任务清单

> 最后更新: 2026-07-15
> 包含 OpenClaw Cron Jobs + Windows Scheduled Tasks

---

## 一、OpenClaw Cron Jobs（LLM AI 定时任务）

共 **13 个**（11 个启用，2 个禁用）

### 盘前时段 (08:00~09:31)

| # | 名称 | 时间 | Cron ID | 状态 | 说明 |
|---|------|------|---------|------|------|
| 1 | **a-stock-data 解禁预警** | 每天 09:00 | `b78b049b` | ✅ 启用 | 检查持仓/观察池 90天/30天解禁, 推送到企微 |
| 2 | **a-stock-data 盘前检查** | 每天 09:05 | `4e361e6e` | ✅ 启用 | 北向资金、行业轮动、盘前信号, 推送到企微 |
| 3 | **新闻信号分析** | 每天 09:10 | `f6a9c400` | ✅ 启用 | 拉取持仓+观察池新闻, LLM分析利好/利空, 写入DB |

### 盘中时段 (09:30~15:00)

| # | 名称 | 时间 | Cron ID | 状态 | 说明 |
|---|------|------|---------|------|------|
| 4 | **req042-intraday-morning** | 09:30~11:30 每30分钟 | `5a3828b6` | ❌ 禁用 | 盘中通知脚本 (已废弃) |
| 5 | **req042-intraday-afternoon** | 13:00~14:30 每30分钟 | `279d99f9` | ❌ 禁用 | 盘中通知脚本 (已废弃) |

### 收盘时段 (15:00~16:00)

| # | 名称 | 时间 | Cron ID | 状态 | 说明 |
|---|------|------|---------|------|------|
| 6 | **a-stock-data 盘后信号日报** | 每天 15:05 | `46cbee8c` | ✅ 启用 | 盘后信号汇总, 推送到企微 |
| 7 | **收盘交易日报** | 每天 15:05 | `58ffd3d7` | ✅ 启用 | 今日交易日报, 推送到企微 |
| 8 | **短线波段扫描-每日收盘** | 交易日 16:00 (±5min) | `3d44112a` | ✅ 启用 | 扫描稳定型股票池, 识别1-2天短线机会 |

### 晚间时段 (18:00~21:00)

| # | 名称 | 时间 | Cron ID | 状态 | 说明 |
|---|------|------|---------|------|------|
| 9 | **研发修复-18点** | 交易日 18:00 (±5min) | `945dbdee` | ✅ 启用 | 检查积压→按P0>P1>P2修复→推修复报告 |
| 10 | **pm-agent-daily-report** | 每天 20:00 (±5min) | `b1ea37e9` | ✅ 启用 | PM Agent汇总所有子agent输出, 发日报 |
| 11 | **理财师-每日复盘汇报** | 每天 20:00 (±5min) | `fdda061a` | ✅ 启用 | 理财师复盘交易并汇报日报 |
| 12 | **研发修复-21点** | 交易日 21:00 (±5min) | `f05ae891` | ✅ 启用 | 检查积压→按P0>P1>P2修复→推修复报告 |

### 次日早间 (09:00)

| # | 名称 | 时间 | Cron ID | 状态 | 说明 |
|---|------|------|---------|------|------|
| 13 | **研发验收-9点** | 交易日 09:00 (±5min) | `8c6cb47a` | ✅ 启用 | 验收fixed任务→verified/退回→推验收报告 |

---

## 二、Windows Scheduled Tasks（系统级定时任务）

共 **24 个**（全部启用）

### 盘前准备 (07:50~09:31)

| # | 名称 | 时间 | 频率 | 脚本/命令 | 说明 |
|---|------|------|------|-----------|------|
| 1 | **QuantLearn_MarketScanner** | 07:50 | 交易日每日 | `market_scanner_runner.bat` | 市场扫描器 |
| 2 | **QuantLearn_CleanupWatchlist** | 08:00 | 交易日每日 | `cleanup_watchlist.py` | 清理观察池 |
| 3 | **QuantLearn_OpsDailyCheck** | 08:00 | 每天 | `ops_daily_check_runner.bat` | 运维每日检查 |
| 4 | **QuantLearn_DailyRecalibrate** | 08:25 | 交易日每日 | `daily_recalibrate.py` | 每日参数校准 |
| 5 | **QuantLearn_MorningScanner** | 08:30 | 交易日每日 | `morning_scanner_runner.bat` | 早盘扫描器 |
| 6 | **QuantLearn_AdvisorPre** | 08:30 | 每天 | `notify_morning_brief.py` | 早盘简报通知 |
| 7 | **QuantLearn_NotifyOpen** | 09:31 | 每天 | `notify_open.py` | 开盘通知 |

### 盘中扫描 (09:00~15:00)

| # | 名称 | 触发时间 | 频率 | 脚本 | 说明 |
|---|------|---------|------|------|------|
| 8 | **QuantLearn_PortfolioAlert** | 09:00~15:00 每30分钟 | 交易日每日 | `portfolio_alert.py` | 持仓预警（13个触发器：09:00, 09:30, 10:00, 10:30, 11:00, 11:30, 12:00, 12:30, 13:00, 13:30, 14:00, 14:30, 15:00） |
| 9 | **QuantLearn_IntradayScanner** | 09:30~14:30 每30分钟 | 交易日每日 | `intraday_scanner.py --top 5` | 盘中扫描（11个触发器：09:30, 10:00, 10:30, 11:00, 11:30, 12:00, 12:30, 13:00, 13:30, 14:00, 14:30） |
| 10 | **QuantLearn_VqlearnLive** | 09:25 | 交易日每日 | `vqlearn_live_runner.bat` | vqlearn 实盘 |
| 11 | **QuantLearn_AdvisorAuction** | 09:15 | 每天 | `notify_auction.py` | 集合竞价通知 |
| 12 | **QuantLearn_AdvisorIntraday** | 10:00, 13:30 | 每天 | `notify_intraday.py` | 盘中顾问通知（2个触发器） |
| 13 | **QuantLearn_Monitor002453_Monday** | 09:20 | 每周一 | `monitor_002453_monday_runner.bat` | 特定股票监控（每周一） |

### 收盘时段 (14:30~15:40)

| # | 名称 | 时间 | 频率 | 脚本 | 说明 |
|---|------|------|------|------|------|
| 14 | **QuantLearn_AdvisorClosing** | 14:30 | 每天 | `notify_review.py --mode summary` | 收盘前简报 |
| 15 | **QuantLearn_AdvisorReview** | 15:15 | 每天 | `notify_review.py --mode review` | 收盘复盘 |
| 16 | **QuantLearn_DailyReview** | 15:30 | 交易日每日 | `daily_review_runner.bat` | 每日复盘 |
| 17 | **QuantLearn_FinanceManager** | 15:30 | 交易日每日 | `finance_manager.py` | 理财经理 |
| 18 | **QuantLearn_GenerateWatchlist** | 15:30 | 每天 | `generate_next_watchlist.py` | 生成次日观察池 |
| 19 | **QuantLearn-理财经理日报** | 15:30 | 每天 | `run_financial_manager_daily.bat` | 理财经理日报 |

### 晚间时段 (18:30~20:00+)

| # | 名称 | 时间 | 频率 | 脚本 | 说明 |
|---|------|------|------|------|------|
| 20 | **QuantLearn_DailyPM_Workflow** | 18:30 | 每天 | `daily_pm_runner.bat` | PM 日报工作流 |
| 21 | **QuantLearn_WeeklyReview** | 15:35 | 每周五 | `weekly_review_runner.bat` | 周度复盘 |
| 22 | **QuantLearn_MonthlyReview** | 每月28日 15:40 | 每月 | `monthly_review_runner.bat` | 月度复盘 |

### 常驻/守护任务

| # | 名称 | 频率 | 脚本 | 说明 |
|---|------|------|------|------|
| 23 | **QuantLearn_PM_Watchdog** | 每5分钟 | `pm_watchdog_runner.bat` | PM 看门狗守护进程 |
| 24 | **QuantLearn_PM_Agent_Hourly** | 每3小时 | `pm_agent_hourly.bat` | PM Agent 轮询 |
| 25 | **QuantLearnDashboard** | 登录时启动 | `web/app.py` | 量化看板 Web 服务 |

---

## 三、时间线总览（交易日）

```
07:50 ─ MarketScanner
08:00 ─ CleanupWatchlist + OpsDailyCheck
08:25 ─ DailyRecalibrate
08:30 ─ MorningScanner + AdvisorPre
09:00 ─ [OpenClaw] 解禁预警 + PortfolioAlert 开始
09:05 ─ [OpenClaw] 盘前检查
09:10 ─ [OpenClaw] 新闻信号分析
09:15 ─ AdvisorAuction
09:20 ─ Monitor002453 (仅周一)
09:25 ─ VqlearnLive
09:30 ─ IntradayScanner + PortfolioAlert 半小时间隔开始
09:31 ─ NotifyOpen
09:30~14:30 ─ IntradayScanner 每30分钟
09:00~15:00 ─ PortfolioAlert 每30分钟
10:00 ─ AdvisorIntraday
13:30 ─ AdvisorIntraday
14:30 ─ AdvisorClosing
15:00 ─ PortfolioAlert 末次
15:05 ─ [OpenClaw] 盘后信号日报 + 收盘交易日报
15:15 ─ AdvisorReview
15:30 ─ DailyReview + FinanceManager + GenerateWatchlist + 理财经理日报
15:35 ─ WeeklyReview (仅周五)
15:40 ─ MonthlyReview (每月28日)
16:00 ─ [OpenClaw] 短线波段扫描
18:00 ─ [OpenClaw] 研发修复
18:30 ─ DailyPM_Workflow
20:00 ─ [OpenClaw] PM日报 + 理财师复盘
21:00 ─ [OpenClaw] 研发修复(二轮)

常驻: PM_Watchdog(5min) + PM_Agent_Hourly(3h) + Dashboard(登录启动)
```

---

## 四、已禁用的任务

| # | 名称 | 禁用原因 |
|---|------|---------|
| 1 | `req042-intraday-morning` | 盘中通知已迁移到 Windows Task `QuantLearn_AdvisorIntraday` |
| 2 | `req042-intraday-afternoon` | 同上 |

---

## 五、注意事项

1. **重复执行**: `IntradayScanner`(11次/日) 和 `PortfolioAlert`(13次/日) 在 09:30~15:00 每30分钟运行，注意日志膨胀
2. **OpenClaw Cron vs Windows Task 重叠**:
   - 收盘15:05~15:30 有大量任务集中触发（OpenClaw 2个 + Windows 5个）
   - 20:00 晚8点 OpenClaw 有 PM日报 + 理财师复盘两个任务同时触发
3. **PM_Watchdog** 每5分钟运行，日志量较大
4. **Dashboard** 以 SYSTEM 用户运行，开机自动启动
