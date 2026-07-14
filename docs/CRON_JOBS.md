# 定时任务清单

> **OpenClaw 怎么跑项目**：以 [DEPLOYMENT.md](./DEPLOYMENT.md) 文首 ★ 章节为准（逐步契约）。  
> 本文是任务对照表；实时层说明见 [REALTIME.md](./REALTIME.md)。  
> 产机：`C:\Users\Administrator\.openclaw\workspace\quant-learn`  
> 时区：`Asia/Shanghai`  
> 更新：2026-07-14

---

## A. 推荐保留（对「挂单建议」有用）

交易相关：**bat / `systemEvent` 直跑**。LLM 只做文案投递。

| 时间 | 任务 | 你收到什么 | 入口 | 推荐调度 |
|:----:|------|-----------|------|----------|
| **08:30** | **宽基选股扫描** | 沪深300+中证500≈800 只 → Top 候选 | `morning_scanner_runner.bat`（fallback） | **建议开** |
| 09:05 | 盘前检查（可选） | 解禁/数据简报 | a-stock-data 技能 | 可选 |
| **盘中 每10分** | **统一脉搏** | 真仓阈值 + 波段机会 + 指数异常 | `quant_pulse_runner.bat` | **必开（推荐）** |
| 盘中 每10分 | 波段盯盘（可被 pulse 覆盖） | 好价买 / 波段止盈止损 | `swing_intraday_watch_runner.bat` | 可与 pulse 二选一 |
| 盘中 5–10min | 真仓阈值（可被 pulse 覆盖） | 你的股到价 | `portfolio_alert_runner.bat` | 可与 pulse 二选一 |
| **盘中 每30分** | **全市场异动** | 量价突破等 → 可进观察池 | `intraday_scanner_runner.bat` | **建议开**（消息会更多） |
| **16:05** | **波段交易日报** | 全日赚/亏 + 挂单复盘 | `swing_daily_report_runner.bat` | **必开** |
| 20:00 | 复盘一句（可选） | 总览 | 理财师短报告 | 可选 |

### 大盘扫不扫？（直接回答）

| | 有没有代码 | 默认推不推 | 你要的话 |
|--|-----------|-----------|---------|
| 盘前宽基≈800 | ✅ `morning_scanner` / fallback | 取决于 schtasks | 开 `MorningScan` |
| 盘中异动≈800 | ✅ `intraday_scanner` | 同上 | 开 `IntradayScanner` |
| 波段蓝筹≈44 | ✅ `swing_intraday_watch` | 应用 pulse | **必开** |
| 你自己的持仓阈值 | ✅ `portfolio_alert` | 应用 pulse | **必开** |

详见 [REALTIME.md](./REALTIME.md)。


### 波段日报行为（必须理解）

```
scripts/swing_daily_report.py
  1. 扫稳定蓝筹池 → swing_scan_results
  2. 账户 #3 swing_trade 模拟买卖（佣金+印花税）
  3. 写 sim_daily_nav → 算今日/累计赚亏
  4. 落盘 output/swing_daily/YYYY-MM-DD.md
  5. 推企微：短结论 + 实盘挂单建议
```

```bat
cd C:\Users\Administrator\.openclaw\workspace\quant-learn
.venv\Scripts\python.exe -u scripts\swing_daily_report.py
REM 可选: --no-trade  --no-push  --skip-scan
```

---

## B. 建议停用 / 合并（减少噪音）

| 现有任务 | 问题 | 建议 |
|----------|------|------|
| 16:00 LLM「短线波段扫描」 | 与 16:05 日报重复 | **停用**，只留 `SwingDaily` |
| 09:00 / 18:00 / 21:00 研发修复 LLM | 半夜改代码、刷屏 | 人触发或每周一次 |
| 20:00 PM Agent 日报 | 研发进度≠挂单建议 | 开发期可留，日常可关 |
| ops-agent-daily（LLM） | 常 LLM 断网失败 | 改 `ops_daily_check_runner.bat` |
| IntradayScanner + MorningScanner + PortfolioAlert 全开 | 盘中消息过多 | **只留 PortfolioAlert** |
| vqlearn_live 全日 auto-trade | 与波段仓双线吵 | 按需开 |

目标：**有效推送 ≤ 每天约 3 条**。

---

## C. Windows schtasks 全量对照

路径前缀：`...\quant-learn\scripts\`

| 任务名（建议） | bat 文件 | 建议时间 | 状态建议 | 说明 |
|----------------|----------|----------|----------|------|
| QuantLearn_SwingDaily | `swing_daily_report_runner.bat` | 16:05 工作日 | **必开** | 波段结论 |
| QuantLearn_QuantPulse | `quant_pulse_runner.bat` | 09:35 起每10分 | **必开** | 真仓+波段+指数脉搏 |
| QuantLearn_MorningScan | `morning_scanner_runner.bat` | 08:30 | **建议开** | 宽基≈800 选股 |
| QuantLearn_IntradayScanner | `intraday_scanner_runner.bat` | 盘中每30分 | **建议开** | 全市场异动 |
| QuantLearn_SwingIntraday | `swing_intraday_watch_runner.bat` | 每10分 | 可被 Pulse 替代 | 仅波段 |
| QuantLearn_PortfolioAlert | `portfolio_alert_runner.bat` | 盘中 | 可被 Pulse 替代 | 仅真仓阈值 |
| QuantLearn_StopLossWatch | `stop_loss_watch_runner.bat` | 盘中 / 09:35 | 可选 | 学习仓止损 |
| QuantLearn_DailyReview | `daily_review_runner.bat` | 15:10 | 可选 | 日复盘 |
| QuantLearn_OpsDailyCheck | `ops_daily_check_runner.bat` | 08:00 | 可选 | 运维（替 LLM ops） |
| QuantLearn_VqlearnLive | `vqlearn_live_runner.bat` | 09:25–15:05 | 按需 | 阈值学习仓 |
| QuantLearn_IntradayScanner | `intraday_scanner_runner.bat` | 盘中 | 可关 | 异动扫 |
| QuantLearn_MorningScanner | `morning_scanner_runner.bat` | 盘前 | 可关 | 早盘扫 |
| QuantLearn_CleanupWatchlist | `cleanup_watchlist_runner.bat` | 08:00 | 可关 | 洗观察池 |
| QuantLearn_FinanceManager | `run_financial_manager_daily.bat` / `finance_manager_runner.bat` | 15:30 | 可关 | 理财经理长文 |
| QuantLearn_WeeklyReview | `weekly_review_runner.bat` | 周五 | 可选 | 周报 |
| QuantLearn_MonthlyReview | `monthly_review_runner.bat` | 月末 | 可选 | 月报 |
| QuantLearn_PmWatchdog | `pm_watchdog_runner.bat` | 小时 | 开发期 | PM 守卫 |
| QuantLearn_MarketScanner | `market_scanner_runner.bat` | — | 可关 | 市场扫 |
| QuantLearn_ReviewMissing | `review_missing_check_runner.bat` | — | 可关 | 缺复盘检查 |

创建示例（波段）：

```bat
schtasks /create /f /tn "QuantLearn_SwingDaily" /tr "C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts\swing_daily_report_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 16:05

REM 盘中波段盯盘：先建 09:35 触发，再在任务计划里设「每 10 分钟重复，持续到 14:50」
schtasks /create /f /tn "QuantLearn_SwingIntraday" /tr "C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts\swing_intraday_watch_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 09:35

schtasks /query /fo LIST | findstr QuantLearn
schtasks /run /tn QuantLearn_SwingDaily
```

---

## D. OpenClaw Cron 全量历史清单（对账用）

> 下表来自仓库历史配置与运维文档汇总。  
> **以产机 `openclaw cron list` 为准**；文档 ID 可能过期或撞号。  
> OpenClaw 部署后应把真实 list 写回 `pm/ops/YYYY-MM-DD-ops.md`。

### D.1 曾出现过的任务

| 时间 | 任务名 | Cron ID（历史） | payload | 建议 |
|:----:|--------|-----------------|---------|------|
| 09:00 | 研发验收 | `945dbdee-28d8-4081-8ba1-22d53ccd5d52` ⚠ | agentTurn | 可关；⚠ 曾与 18:00 疑似同 ID |
| 09:00 | a-stock-data 解禁预警 | `f05ae891-9721-4e64-94df-fff27f561f0b` | agentTurn | 可选保留 |
| 09:05 | a-stock-data 盘前检查 | `8c6cb47a-f857-462b-bb4d-d792105a7e82` | agentTurn | 可选；可改 systemEvent |
| 09:10 | 新闻信号分析 | `b78b049b-9c02-4c2b-8c3d-d019af710489` | agentTurn | 可关 |
| 14:05 | 新闻信号（盘中） | `4e361e6e-c29a-494d-bd87-de07d0a48645` | agentTurn | 可关 |
| 15:05 | a-stock-data 盘后信号日报 | `f6a9c400-05c1-40fd-9935-8805c064ad78` | agentTurn | 可关（与波段日报重叠） |
| 15:05 | 收盘交易日报 | `46cbee8c-1be8-40b0-b6bf-11b5a8ca452a` | agentTurn | 可选；或改 bat |
| 16:00 | 短线波段扫描-每日收盘 | `58ffd3d7-7199-4290-b48e-fc0f9268c06f` | agentTurn | **停用** → 改 16:05 SwingDaily |
| 18:00 | 研发修复-18点 | `945dbdee-...` ⚠ | agentTurn | 可关 |
| 19:00 | ops-agent-daily | `7835f916-cb1f-485e-863a-adcd4857653e` | agentTurn | 改 bat |
| 20:00 | pm-agent-daily-report | `b1ea37e9-8d69-408e-a5ed-42e0d059acd9` | agentTurn | 开发期可选 |
| 20:00 | 理财师-每日复盘汇报 | `fdda061a-a098-4499-9914-9326082171b1` | agentTurn | 可关或缩短 |
| 21:00 | 研发修复-21点 | `3d44112a-cf63-4233-8522-209edeee9719` | agentTurn | 可关 |

非交易日：历史上仅 `pm-agent-daily-report`（`0 20 * * *`）仍跑。

### D.2 添加任务 — systemEvent（交易/扫描推荐）

```json
{
  "name": "波段交易日报",
  "schedule": {
    "kind": "cron",
    "expr": "5 16 * * 1-5",
    "tz": "Asia/Shanghai"
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "systemEvent",
    "command": ".venv\\Scripts\\python.exe -u scripts\\swing_daily_report.py"
  },
  "delivery": {
    "mode": "announce",
    "channel": "wecom",
    "to": "jizhouhu"
  }
}
```

### D.3 添加任务 — agentTurn（仅报告文案）

```json
{
  "name": "任务名称",
  "schedule": {
    "kind": "cron",
    "expr": "分 时 日 月 周",
    "tz": "Asia/Shanghai",
    "staggerMs": 300000
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "任务提示词…（禁止直接改交易代码上生产）",
    "model": "gongfeng/deepseek-v4-pro",
    "timeoutSeconds": 0
  },
  "delivery": {
    "mode": "announce",
    "channel": "wecom",
    "to": "jizhouhu"
  }
}
```

### D.4 注意事项

- `sessionTarget: isolated`
- 需要推送：`delivery.mode=announce`（勿 `none`）
- 工作日：`1-5`；同时刻加 `staggerMs`
- 大需求勿让夜间修码 cron 碰：REQ-011 / REQ-043 / REQ-019
- 路径必须在项目根，且存在 `.venv\Scripts\python.exe`

---

## E. OpenClaw 对账口令

```text
1. 运行 openclaw cron list 与 schtasks /query | findstr QuantLearn
2. 对照 docs/CRON_JOBS.md 章节 C、D
3. 确保 QuantLearn_SwingDaily 或等价 systemEvent 在 16:05 存在且唯一（删掉重复的 LLM 波段扫描）
4. 试跑一次 swing_daily_report.py --no-push，确认 output/swing_daily/ 有今日文件
5. 将真实 ID 清单写入 pm/ops/今天-ops.md，并在 CRON 文档 D 节旁备注「已对账」
```

---

## F. 账户与产出物

| 账户 | id | 用途 |
|------|----|------|
| learn | 1 | 阈值学习 |
| real_portfolio | 2 | 真实持仓镜像 |
| swing_trade | 3 | 波段模拟（日报赚亏） |

| 产出 | 路径 |
|------|------|
| 波段结论 | `output/swing_daily/YYYY-MM-DD.md` |
| 波段 JSON | `output/swing_daily/YYYY-MM-DD.json` |
| 结论表 | DB `swing_daily_conclusions` |
| 净值 | DB `sim_daily_nav`（account_id=3） |
