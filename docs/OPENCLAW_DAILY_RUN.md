# OpenClaw 每日运行手册（读完按做）

> **给谁读**：OpenClaw Agent / 产机运维  
> **产机路径（写死）**：`C:\Users\Administrator\.openclaw\workspace\quant-learn`  
> **目标**：交易脚本按时跑；晚间把台账 / PM / 研发 / 测试落盘 **自动 push 到 `master`**  
> **权威对照**：[DEPLOYMENT.md](./DEPLOYMENT.md) · [CRON_JOBS.md](./CRON_JOBS.md) · [REVIEW_LOOP.md](./REVIEW_LOOP.md)

---

## 0. 红线（违反即停）

1. **禁止**用 LLM `agentTurn` 扫盘、模拟下单、改交易核心代码并自动 merge。  
2. **禁止** `git push --force` / 改 webhook / 提交 `config.local.yaml` / `*.db`。  
3. 交易类任务 **只用 Windows schtasks 跑 `.bat`**；OpenClaw LLM cron **最多 1～2 条**（只写 `pm/` 文案）。  
4. 晚间推仓库用 **`QuantLearn_DailyGitSync`（脚本）**，不要让 LLM 自己乱 `git push`。

---

## 1. 一天怎么跑（你要保证这套在）

```
【Windows schtasks — 交易，不占 LLM】
08:30            MorningScan
08:40            SwingPool Top20
09:35~14:50 /10m QuantPulse（GUI 设 10 分重复）
10:00~14:30 /30m IntradayScanner（可选）
16:05            SwingDaily
16:15            TradeJournal → pm/trade_journal/
16:20            DailyClose

【OpenClaw LLM — 最多 1～2 条】
16:30            理财：填台账「复盘备注」；有问题开 BUG/REQ
17:00~18:15      需求/PM/QA/开发经理：入库 + 写 cursor_queue（可合并成 18:15 一条）

【Windows schtasks — 推 master】
18:45            DailyGitSync → 白名单 commit + push origin/master
```

---

## 2. 首次部署检查清单（按顺序执行）

在产机 **cmd**（管理员可选）：

```bat
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
git pull --ff-only origin master
```

确认存在：

```bat
dir scripts\daily_git_sync.py
dir scripts\daily_git_sync_runner.bat
```

挂 / 刷新 schtasks（`ROOT` 按产机路径）：

```bat
set ROOT=C:\Users\Administrator\.openclaw\workspace\quant-learn

schtasks /create /f /tn "QuantLearn_MorningScan"    /tr "%ROOT%\scripts\morning_scanner_runner.bat"    /sc weekly /d MON,TUE,WED,THU,FRI /st 08:30
schtasks /create /f /tn "QuantLearn_SwingPool"      /tr "%ROOT%\scripts\swing_pool_builder_runner.bat"  /sc weekly /d MON,TUE,WED,THU,FRI /st 08:40
schtasks /create /f /tn "QuantLearn_QuantPulse"     /tr "%ROOT%\scripts\quant_pulse_runner.bat"         /sc weekly /d MON,TUE,WED,THU,FRI /st 09:35
schtasks /create /f /tn "QuantLearn_IntradayScanner" /tr "%ROOT%\scripts\intraday_scanner_runner.bat"   /sc weekly /d MON,TUE,WED,THU,FRI /st 10:00
schtasks /create /f /tn "QuantLearn_SwingDaily"     /tr "%ROOT%\scripts\swing_daily_report_runner.bat"  /sc weekly /d MON,TUE,WED,THU,FRI /st 16:05
schtasks /create /f /tn "QuantLearn_TradeJournal"   /tr "%ROOT%\scripts\trade_journal_runner.bat"       /sc weekly /d MON,TUE,WED,THU,FRI /st 16:15
schtasks /create /f /tn "QuantLearn_DailyClose"     /tr "%ROOT%\scripts\daily_close_report_runner.bat"  /sc weekly /d MON,TUE,WED,THU,FRI /st 16:20
schtasks /create /f /tn "QuantLearn_DailyGitSync"   /tr "%ROOT%\scripts\daily_git_sync_runner.bat"      /sc weekly /d MON,TUE,WED,THU,FRI /st 18:45

schtasks /query /fo LIST | findstr QuantLearn
```

**GUI 必补：**

1. `QuantLearn_QuantPulse` → 重复间隔 **10 分钟**，到 **14:50**  
2. `QuantLearn_IntradayScanner`（若开）→ 重复 **30 分钟**，到 **14:30**

试跑推送：

```bat
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
.venv\Scripts\python.exe -u scripts\daily_git_sync.py --dry-run
schtasks /run /tn QuantLearn_DailyGitSync
type output\daily_git_sync.log
git log -1 --oneline
git status -sb
```

---

## 3. OpenClaw Cron（只留文案）

```bat
openclaw cron list
```

| 处理 | 内容 |
|------|------|
| **全部删/停** | 任何交易扫描、波段扫描、每 N 分钟盯盘的 `agentTurn` |
| **最多 1～2 条** | 晚间：入库 + 写 `pm/cursor_queue`（建议 **18:15 一条合并**） |
| **不要** | schtasks 已跑的脚本再挂一份 LLM（双推） |

### 推荐唯一 LLM 任务提示词（约 18:15）

把下面整段贴进 OpenClaw cron `agentTurn`：

```text
你是 OpenClaw 治理 Agent。工作目录：
C:\Users\Administrator\.openclaw\workspace\quant-learn
先读 docs/OPENCLAW_DAILY_RUN.md 与 docs/REVIEW_LOOP.md，再执行。

禁止：改交易核心代码；force push；提交密钥/config.local/*.db；自己 git push。

今日必须落盘（没有就创建）：
1) 读 pm/trade_journal/今天.md；若「复盘备注」空，补短备注（做对/做错/明日关注）。
2) 扫 output/ / 台账 / 企微相关日志，发现的问题一律入库：
   - pm/bugs/BUG-xxx.md 或 pm/requirements/REQ-xxx.md
   - 可用：.venv\Scripts\python.exe scripts\pm_cli.py create ...
3) QA：若跑了测试，写 pm/test_reports/；失败则 reopen 对应 BUG。
4) 开发经理：对将进队列的 P0/靠前 P1，在 pm/dev/ 写最短 PLAN-*.md（路径+验收）。
5) PM：写完整 pm/cursor_queue/今天.md（P0+P1+P2 全量，不要只留 3 条 P0）。
6) 企微短摘要：P0x/P1x/P2x + 提醒主人用 Cursor 话术「按 cursor_queue 从顶往下做」。

落盘即可。18:45 的 QuantLearn_DailyGitSync 会白名单 commit+push master。
结束后在回复里列出：新建/更新了哪些文件路径。
```

理财单独短任务（可选 16:30，也可并进上面）：

```text
【交易复盘备注】不改成交数字。
1. 必要时跑 .venv\Scripts\python.exe -u scripts\trade_journal.py --no-push
2. 填 pm/trade_journal/今天.md 文末「复盘备注」
3. 发现问题 → 开 BUG/REQ 文件，不要只吐槽
```

---

## 4. DailyGitSync 推什么 / 不推什么

脚本：`scripts/daily_git_sync.py`  
日志：`output/daily_git_sync.log`

**会推（白名单）：**

- `pm/trade_journal/` — 交易台账  
- `pm/cursor_queue/` — Cursor 修复队列  
- `pm/requirements/` · `pm/bugs/` — 需求/缺陷  
- `pm/dev/` — PLAN  
- `pm/test_reports/` — 测试报告  
- `pm/ops/` — 运维/部署记录  
- `output/swing_daily/` · `output/swing_pool/` · `output/daily_close_*.md`

**绝不推：**

- `scripts/` / `vqlearn/` / `quant_core/` / `strategies/` 等交易代码  
- `tests/`、`sim/`、`web/`（代码改动走人工/Cursor 正常 PR 流程）  
- `*.db`、`config.local.yaml`、`.env`、`.venv/`

手动：

```bat
.venv\Scripts\python.exe -u scripts\daily_git_sync.py --dry-run
.venv\Scripts\python.exe -u scripts\daily_git_sync.py
.venv\Scripts\python.exe -u scripts\daily_git_sync.py --no-push
```

---

## 5. 主人（Cursor）晚上怎么接

```text
按 pm/cursor_queue/今天.md 从顶往下做，能做多少做多少，不限 P0。
每项单独 commit；做完打勾并用 pm_cli 改状态。
```

代码修复由主人/Cursor push；**不要**指望 DailyGitSync 推业务代码。

---

## 6. 每日自检（OpenClaw 可在心跳/收工时做）

```bat
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
git pull --ff-only origin master
schtasks /query /fo LIST | findstr QuantLearn
dir pm\trade_journal
dir pm\cursor_queue
type output\daily_git_sync.log
openclaw cron list
```

健康标准：

| 项 | 期望 |
|----|------|
| QuantLearn_TradeJournal | 有；当日 `pm/trade_journal/YYYY-MM-DD.md` 存在 |
| QuantLearn_DailyGitSync | 有；日志无 push 失败 |
| OpenClaw 交易 LLM cron | **0 条** |
| OpenClaw 文案 LLM | **≤2 条** |
| cursor_queue | 交易日晚间有「今天」文件 |

异常写入：`pm/ops/YYYY-MM-DD-openclaw-check.md`（简述失败命令与原文）。

---

## 7. 一句话给主人

> 交易靠 Windows 任务计划；OpenClaw 只写 `pm/`；18:45 脚本把台账和各 Agent 运行落盘推到 `master`。

完。
