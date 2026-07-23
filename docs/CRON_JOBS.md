# 定时任务清单

> **权威跑法**：[DEPLOYMENT.md](./DEPLOYMENT.md) ★ 章节  
> **实时层**：[REALTIME.md](./REALTIME.md) · **复盘**：[REVIEW_LOOP.md](./REVIEW_LOOP.md)  
> 产机：`C:\Users\Administrator\.openclaw\workspace\quant-learn` · 时区 `Asia/Shanghai`  
> 更新：2026-07-24（补 18:45 DailyGitSync 必开 + 19:15 OpenClaw 守夜）

---

## ⚠️ 两套定时器，别混

| 哪套 | 是什么 | 干什么 | 个数 |
|------|--------|--------|------|
| **Windows 任务计划** `schtasks` | 跑 `.bat` / python，**不占 LLM** | **全部交易扫描、Pulse、波段、台账、推 master** | 可多开 |
| **OpenClaw Cron** | `openclaw cron` | **文案落盘 + ★守夜验货**（禁止用来每 10 分钟扫盘） | **有限额** |

盘中「每 10 分 / 每 30 分」= 在 **Windows「任务计划程序」GUI** 里给对应 schtasks 勾「重复任务间隔」，**不是**给 OpenClaw 挂一堆 LLM cron。

---

## 一天长什么样（推荐态）

```mermaid
flowchart TD
  A["08:30 MorningScan 宽基选股"] --> A2["08:40 SwingPool 方法池≤50"]
  A2 --> B["09:35-14:50 QuantPulse 每10分"]
  B --> C["10:00-14:30 IntradayScanner 可选"]
  B --> D["16:05 SwingDaily 波段结论"]
  D --> E["16:15 TradeJournal 台账"]
  E --> F["16:20 daily_close 双账户摘要"]
  F --> G["16:30-18:15 OpenClaw 复盘入库 + Cursor队列"]
  G --> H["18:45 DailyGitSync push master"]
  H --> I["19:15 OpenClaw 守夜验货"]
```

| 时刻 | 任务 | **定时器在哪** | 入口 | 说明 |
|:----:|------|----------------|------|------|
| **08:30** | 宽基选股 | **Windows schtasks** | `morning_scanner_runner.bat` | 早上找票 |
| **08:40** | 动态稳定池+盘前机会 | **Windows schtasks** | `swing_pool_builder_runner.bat` | 方法过滤+软上限50 → `swing_auto` 推企微 |
| **09:35→14:50 /10m** | 统一脉搏 | **Windows schtasks** + **任务计划 GUI 重复间隔 10 分** | `quant_pulse_runner.bat` | 真仓+波段+指数；**不要**开 LLM cron |
| **10:00→14:30 /30m** | 全市场异动 | **Windows schtasks** + **GUI 重复 30 分**（可选） | `intraday_scanner_runner.bat` | 吵可关；**不要**开 LLM cron |
| **16:05** | 波段日报 | **Windows schtasks** | `swing_daily_report_runner.bat` | #3 赚亏+挂单建议 |
| **16:15** | 交易台账 | **Windows schtasks** | `trade_journal_runner.bat` | `pm/trade_journal/` |
| **16:20** | 双账户摘要 | **Windows schtasks** | `daily_close_report_runner.bat` | #1+#3 |
| **16:30** | 复盘备注 | **OpenClaw cron（agentTurn）最多 1 条** | 短提示词 | 只写 md |
| **17:00** | 需求入库 | **可与 18:15 合并成 1 条** OpenClaw | 短提示词 | 写 `pm/` |
| **18:15** | Cursor 队列 | **OpenClaw cron 1 条够** | 短提示词 | 写 `cursor_queue` |
| **18:45** | 治理产物推 master | **Windows schtasks** | `daily_git_sync_runner.bat` | 台账/PM/QA/Ops 白名单 push |
| **19:15** | ★守夜验货 | **OpenClaw cron（必留）** | OPENCLAW_DAILY_RUN §3 任务 B | 远程无今日台账 → 补跑 + 企微告警 |

**OpenClaw 侧**：交易类 **0** 条 LLM；文案 **≤2** 条；**守夜 1 条必留**。晚间 **push 用 schtasks**；守夜只负责验收/补跑脚本，别让 LLM 乱 `git add scripts/`。

### 必开 vs 可选（别纠结）

| 级别 | 任务名 | 说明 |
|------|--------|------|
| **必开** | `QuantLearn_QuantPulse` | 盘中主心跳；已含真仓+波段盯盘 |
| **必开** | `QuantLearn_SwingPool` | 08:40 方法过滤池(≤50) + 盘前波段扫描推企微 |
| **必开** | `QuantLearn_SwingDaily` | 收盘波段结论 |
| **必开** | `QuantLearn_TradeJournal` | 每日交易记录 |
| **必开** | `QuantLearn_DailyClose` | 收盘双账户摘要 |
| **必开** | `QuantLearn_DailyGitSync` | **18:45 推 master**（上传主职；漏挂=主人永远拉不到） |
| **必开** | OpenClaw **19:15 守夜** | 验货+补跑；提示词见 OPENCLAW_DAILY_RUN |
| **建议开** | `QuantLearn_MorningScan` | 盘前宽基 |
| **消息多再关** | `QuantLearn_IntradayScanner` | 异动扫；吵就关 |
| **勿双开** | `SwingIntraday` / `PortfolioAlert` | 已被 Pulse 覆盖时请关，防重复推送 |

---

## A. 扫描层一句话

| 扫什么 | 有没有 | 谁推 |
|--------|:------:|------|
| 盘前宽基 ≈800 | ✅ | MorningScan |
| 动态稳定池≤50 | ✅ | SwingPool → Pulse/SwingDaily |
| 盘中异动 ≈800 | ✅ | IntradayScanner（可选） |
| 你的持仓阈值 | ✅ | **QuantPulse 内嵌** |

---

## B. 建议停用（减噪）

| 现状 | 问题 | 处理 |
|------|------|------|
| 16:00 LLM「短线波段扫描」 | 与 16:05 SwingDaily 重复 | **停** |
| 单独 `PortfolioAlert` + `SwingIntraday` + Pulse 全开 | 同一事推三次 | **只留 Pulse** |
| 09/18/21 研发修码 LLM | 乱改代码 | **停**，改走 Cursor 队列 |
| ops / 理财师超长 LLM | 易超时 | 改 bat 或缩短提示 |

目标：**有效企微 ≤ 每天约 3～5 条**（不含盘中到价必达）。

---

## C. schtasks 模板（复制）

```bat
set ROOT=C:\Users\Administrator\.openclaw\workspace\quant-learn

schtasks /create /f /tn "QuantLearn_MorningScan"    /tr "%ROOT%\scripts\morning_scanner_runner.bat"    /sc weekly /d MON,TUE,WED,THU,FRI /st 08:30
schtasks /create /f /tn "QuantLearn_SwingPool"      /tr "%ROOT%\scripts\swing_pool_builder_runner.bat"  /sc weekly /d MON,TUE,WED,THU,FRI /st 08:40
schtasks /create /f /tn "QuantLearn_QuantPulse"     /tr "%ROOT%\scripts\quant_pulse_runner.bat"         /sc weekly /d MON,TUE,WED,THU,FRI /st 09:35
schtasks /create /f /tn "QuantLearn_IntradayScanner" /tr "%ROOT%\scripts\intraday_scanner_runner.bat"   /sc weekly /d MON,TUE,WED,THU,FRI /st 10:00
schtasks /create /f /tn "QuantLearn_SwingDaily"     /tr "%ROOT%\scripts\swing_daily_report_runner.bat"  /sc weekly /d MON,TUE,WED,THU,FRI /st 16:05
schtasks /create /f /tn "QuantLearn_TradeJournal"   /tr "%ROOT%\scripts\trade_journal_runner.bat"       /sc weekly /d MON,TUE,WED,THU,FRI /st 16:15
schtasks /create /f /tn "QuantLearn_DailyGitSync"   /tr "%ROOT%\scripts\daily_git_sync_runner.bat"      /sc weekly /d MON,TUE,WED,THU,FRI /st 18:45

schtasks /query /fo LIST | findstr QuantLearn
```

**GUI 必须补两刀**（schtasks 创建后进「任务计划程序」）：

1. `QuantLearn_QuantPulse` → 重复间隔 **10 分钟**，持续到 **14:50**  
2. `QuantLearn_IntradayScanner` → 重复间隔 **30 分钟**，持续到 **14:30**

全量可选对照：

| 任务名 | bat | 建议 |
|--------|-----|------|
| QuantLearn_MorningScan | `morning_scanner_runner.bat` | 建议开 |
| QuantLearn_SwingPool | `swing_pool_builder_runner.bat` | **必开**（08:40 建池≤50 + `swing_auto` 盘前推企微） |
| QuantLearn_QuantPulse | `quant_pulse_runner.bat` | **必开** |
| QuantLearn_IntradayScanner | `intraday_scanner_runner.bat` | 建议开 / 吵则关 |
| QuantLearn_SwingDaily | `swing_daily_report_runner.bat` | **必开** |
| QuantLearn_TradeJournal | `trade_journal_runner.bat` | **必开** |
| QuantLearn_DailyGitSync | `daily_git_sync_runner.bat` | **必开**（18:45 台账/PM/QA 推 master） |
| QuantLearn_SwingIntraday | `swing_intraday_watch_runner.bat` | Pulse 已开则关 |
| QuantLearn_PortfolioAlert | `portfolio_alert_runner.bat` | Pulse 已开则关 |
| QuantLearn_StopLossWatch | `stop_loss_watch_runner.bat` | 学习仓用，可选 |
| QuantLearn_VqlearnLive | `vqlearn_live_runner.bat` | 按需（与 #3 双线会吵） |
| QuantLearn_DailyReview | `daily_review_runner.bat` | 可选（台账已覆盖大半） |
| QuantLearn_OpsDailyCheck | `ops_daily_check_runner.bat` | 可选 |
| QuantLearn_WeeklyReview | `weekly_review_runner.bat` | 周五可选 |

### 波段日报在干什么

```
swing_daily_report.py
  → 扫动态稳定池(方法合格≤50) → #3 模拟买卖（佣金+印花）
  → sim_daily_nav → output/swing_daily/今天.md
  → 企微短结论 + 实盘挂单建议；成交成功另发 @all 同步提醒
```

### 动态稳定池（方法过滤 + 软上限）

- `scripts/swing_pool_builder.py`：沪深300+中证500 → 硬过滤 → `score≥70` 入池 → **软上限 50**
- 每天重排：不够格出局、够格进来；账户 #3 持仓强制保留
- 产物：`output/swing_pool/latest.json`（含 entered/exited）
- 盘中 Pulse / 收盘 SwingDaily 都读这个池；缺失则回退旧种子蓝筹
- 模拟买卖成功 → `swing_intraday_watch.push_sync_trade`：**text + @all「立刻同步实盘」**
---

## D. OpenClaw Cron（对账用）

> 以产机 `openclaw cron list` 为准。交易类优先 **schtasks bat**，不要 agentTurn 扫盘/下单。

| 时间 | 历史名 | 建议 |
|:----:|--------|------|
| 16:00 | 短线波段扫描 LLM | **停** → SwingDaily |
| 16:30 | （新建）交易复盘备注 | agentTurn 短任务，见 REVIEW_LOOP §12 |
| 18:15 | （新建）PM 写 Cursor 队列 | agentTurn，见 REVIEW_LOOP §11 |
| 09/18/21 | 研发修码 | **停** |
| 19:00 | ops-agent LLM | 改 `ops_daily_check_runner.bat` |

systemEvent 示例（若不用 schtasks）：

```json
{
  "name": "交易台账",
  "schedule": { "kind": "cron", "expr": "15 16 * * 1-5", "tz": "Asia/Shanghai" },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "systemEvent",
    "command": ".venv\\Scripts\\python.exe -u scripts\\trade_journal.py"
  },
  "delivery": { "mode": "announce", "channel": "wecom", "to": "jizhouhu" }
}
```

---

## E. 对账口令

```text
1. openclaw cron list
2. schtasks /query /fo LIST | findstr QuantLearn
3. 必有：QuantPulse / SwingDaily / TradeJournal；建议有 MorningScan
4. 无：与 SwingDaily 重复的 LLM 波段扫描；无 Pulse+PortfolioAlert+SwingIntraday 三重推送
5. 试跑 trade_journal.py --no-push → pm/trade_journal/今天.md 存在
6. 清单写入 pm/ops/今天-ops.md
```

---

## F. 账户与产出

| id | 名 | 用途 |
|----|----|------|
| **1** | learn | **模拟学习仓**（主推企微） |
| 2 | real_portfolio | 真仓镜像（可选，默认可不看） |
| **3** | swing_trade | **波段模拟**（挂单建议看这个） |

> 主人约定日常 **只盯 #1 + #3**。  
> 旧 bug：`daily_close_report` 曾把「当日盈亏」写成 `总资产-100000` → 出现 +119% 鬼畜数字（2026-07-15 已修）。

| 产出 | 路径 |
|------|------|
| 波段结论 | `output/swing_daily/YYYY-MM-DD.md` |
| 交易台账 | `pm/trade_journal/YYYY-MM-DD.md` |
| Pulse 日志 | `output/quant_pulse.log` |
| 成交 | DB `sim_trades` |
| 净值 | DB `sim_daily_nav` |
