# BUG-20260723-001：交易日台账未上传 origin/master

**发现日期**: 2026-07-24 00:50  
**严重程度**: P0（主人次日拉不到台账 = 部署失职）  
**状态**: open

## 现象

- 仓库最新提交停在 `052995f`（2026-07-22 18:58）
- **无** `pm/trade_journal/2026-07-23.*`
- **无** `output/daily_close_2026-07-23.md`
- **无** `output/swing_daily/2026-07-23.*`
- 2026-07-23 为周四交易日，18:45 `QuantLearn_DailyGitSync` 应已推送

## 根因（文档/提示词层）

1. 上传主职在 **Windows schtasks `DailyGitSync`**，不是 OpenClaw LLM。
2. 旧 18:15 提示词写「落盘即可，18:45 会推」→ Agent **不验收远程**，schtasks 挂了也静默。
3. 自检写成「可在心跳时做」→ 可选；无 19:15 守夜硬任务。
4. `CRON_JOBS.md` 旧「必开」表甚至漏列 `DailyGitSync` / `DailyClose`。

可能叠加的产机层原因（需上机确认）：睡眠/关机、任务禁用、Last Result≠0、本地都没生成台账。

## 修复

- 文档已改（2026-07-24）：`OPENCLAW_DAILY_RUN.md` / `DEPLOYMENT.md` / `CRON_JOBS.md` / `REVIEW_LOOP.md`
  - 硬 SLO：次日 origin 必须有昨台账
  - 新增 **19:15 守夜** 提示词（验货+补跑+企微【量化失职】）
- 产机待办：`git pull` 后挂守夜 cron；试跑 TradeJournal + DailyClose + DailyGitSync；禁睡眠

## 验收

1. 产机 `openclaw cron list` 含 19:15 守夜  
2. `schtasks` 有 DailyGitSync 且试跑后 `git log origin/master` 出现当日 `chore(daily)` 或台账文件  
3. 连续 2 个交易日主人 `git pull` 能看到前一日台账  
