# 每日复盘与多角色迭代规划（OpenClaw 轻量 + Cursor 重活）

> **问题**：OpenClaw 模型弱 → 不能乱改仓。  
> **解法**：**OpenClaw 把问题/需求全部写进仓库 `pm/`**；**晚上 Cursor 按队列尽量多修**（不限只做 P0）。  
> 更新：2026-07-15

配套：`pm/agents/*`、`scripts/pm_cli.py`。旧「Dev Agent 自动改代码」**作废**，以本文为准。

---

## 1. 目标一句话

```
OpenClaw 全量写 REQ/BUG → pm/requirements + pm/bugs + pm.db
     → 每晚生成「给 Cursor 的完整修复队列」
     → 你在 Cursor 说「按队列从顶往下做」→ 能修多少修多少 → commit → push
```

OpenClaw **不藏需求在聊天里**；没写进项目 = 没存在过。  
Cursor **不卡死在「只做 3 条 P0」**；有空就扫完整队列。

---

## 2. 角色分工

| 角色 | OpenClaw | 做什么 | **禁止** |
|------|----------|--------|----------|
| 理财 | ✅ | 填台账复盘备注；发现问题 → 提 REQ/BUG | 改策略代码 |
| **需求** | ✅ | **发现的问题一律入库**（md + pm_cli）；去重；标 P0/P1/P2 | 写实现代码 |
| **PM** | ✅ | 整理 backlog → **完整** `cursor_queue/今天.md`；企微摘要 | 大改代码 |
| 开发经理 | ⚠️ | 给队列里可动手的项写 `PLAN-*.md`（路径+验收） | 擅自大范围 commit |
| QA | ✅ | pytest / 报告；失败 reopen | 改断言凑绿 |
| Ops | ✅ | 调度/日志问题开 Bug | 乱删任务 |
| **Cursor** | — | **按队列修代码，尽量多做** | — |

---

## 3. 状态机 + 落盘（必须进 git）

```
REQ:  pending → ready → in_progress → testing → done → deployed
BUG:  open → in_progress → fixed → verified → deployed
```

```bat
.venv\Scripts\python.exe scripts\pm_cli.py create --type story --title "..." --priority P1
.venv\Scripts\python.exe scripts\pm_cli.py update REQ-048 --status testing
.venv\Scripts\python.exe scripts\pm_cli.py list --status pending
```

| 类型 | 路径 | 规则 |
|------|------|------|
| 需求 | `pm/requirements/REQ-xxx.md` | **每条发现都要有文件**，禁止只口头提 |
| Bug | `pm/bugs/BUG-xxx.md` | 同上 |
| 方案 | `pm/dev/PLAN-*.md` | Cursor 动手前应有；没有则 Cursor 先补最短方案 |
| **Cursor 队列** | `pm/cursor_queue/YYYY-MM-DD.md` | **每晚必有，含全量可做项** |
| 台账 | `pm/trade_journal/` | 脚本事实 |
| 测试 | `pm/test_reports/` | QA |

**入库原则**

1. 聊天/企微里提到的缺陷 → 当天必须变成 `pm/bugs` 或 `pm/requirements` 文件  
2. 去重：同症状合并，不重复开单  
3. 大需求（vnpy Oms、架构重构）→ 仍入库，标 `epic` / 放队列「本周不做」区  
4. **不再限制「每天新建 ≤3」**；可执行小单优先标 P0/P1，但 P2 也要写进仓库

---

## 4. 每日时间线

| 时间 | 谁 | 动作 |
|:----:|----|------|
| 16:05–16:15 | 脚本 | 波段日报 + 交易台账 |
| 16:30 | 理财 | 填复盘备注；有问题就开 BUG/REQ |
| **17:00** | **需求+PM** | **扫日志/复盘/企微 → 全量入库去重** |
| 17:30 | QA | pytest 结果入库 / reopen |
| 18:00 | 开发经理 | 给队列前段写 PLAN（P0+P1 尽量全覆盖） |
| **18:15** | **PM** | 写 **完整** `pm/cursor_queue/今天.md` + commit 或等 18:45 统一同步 |
| 18:30 | PM | 企微：今日队列条数（P0/P1/P2 计数）+ Cursor 一键话术 |
| **18:45** | **schtasks** | **`QuantLearn_DailyGitSync`**：台账/PM/QA/Ops 白名单 `commit + push master` |
| **20:00** | OpenClaw | LLM 各类日报落盘 `daily_reports/`（DEPLOYMENT 提示词 C） |
| **20:30** | **schtasks** | **`QuantLearn_DailyGitSyncEvening`**：同 bat，推 LLM 日报 |
| **晚上** | **你+Cursor** | **按队列从上到下尽量做完**，每项单独 commit；代码改动你自己 push |
| **19:30**（可选） | **本机 cron** | `scripts/cursor_queue_auto_runner.sh` 无头消费队列 → 只推 feature 分支；你验收 MR（见 DEPLOYMENT「本机 Cursor 队列自动消费」） |
| 次日盘前 | PM/QA | 对昨夜 commit 改状态 |

---

## 5. Cursor 队列格式（完整菜单）

`pm/cursor_queue/YYYY-MM-DD.md`

```markdown
# Cursor 修复队列 2026-07-15

> 主人在 Cursor 说：按本文件从上方往下做，能做多少做多少；不限 P0。
> 每项单独 commit；做完打勾并 pm_cli 改状态。

## 统计
- P0: N | P1: N | P2: N | 本周不做: N

## P0（今晚优先）
### 1. REQ-xxx 标题
- 状态: pending
- 文档: pm/requirements/REQ-xxx.md
- 方案: pm/dev/PLAN-REQ-xxx.md
- 关键文件: a.py, b.py
- 验收: pytest … 
- 做完: pm_cli update REQ-xxx --status testing

## P1（接着做）
### 1. …
## P2（有空继续）
- BUG-… / REQ-…（一行摘要 + 路径即可）

## 本周不做（已入库，勿删）
- REQ-011 vnpy OmsEngine — 太大，另开专轮

## 不要动
- config.local.yaml / webhook
- 勿 force push
```

### 你在 Cursor 一键话术（复制）

```text
读 pm/cursor_queue/今天的日期.md（没有就用最新一天）。
规则：从 P0 → P1 → P2 尽量多修，不要只做 P0 就停。
每项：读 REQ/BUG + PLAN（无则先写 10 行方案）→ 改代码 → 跑验收 pytest → 通过则 pm_cli 改状态 → 队列打勾 → 单独 commit。
全部能做的做完后 git push（除非我另说）。
不碰「不要动」与「本周不做」。
```

### 本机自动消费（可选）

不想每晚手动画话术时，可在本机挂 Linux cron 跑 `scripts/cursor_queue_auto_runner.sh`（方案 A）：

- 仍读同一份 `pm/cursor_queue/今天.md`
- 默认 `CURSOR_AUTO_MAX_ITEMS=1`，开 `feat/cursor-auto-*`，**只推 feature 分支**
- 人工开/验收 MR；**绝不**自动推 master
- 详见 [DEPLOYMENT.md](./DEPLOYMENT.md)「本机 Cursor 队列自动消费」与 [CRON_JOBS.md](./CRON_JOBS.md)

---

## 6. OpenClaw 提示词

### 需求入库（17:00）— 核心

```text
你是需求+PM 助理。禁止改 strategies/scripts 业务代码。

目标：今天发现的问题/想法【全部】写入项目，禁止只留在对话里。

1. 读：pm/trade_journal/今天.md、output/swing_daily/、output/*.log 尾部、
   pm/bugs、pm/requirements、ROADMAP、企微/运维提到的异常
2. list 已有单 → 去重合并
3. 新问题：写 pm/requirements/REQ-xxx.md 或 pm/bugs/BUG-xxx.md
   + pm_cli create（priority 标 P0/P1/P2）
4. 文件必须含：现象、复现/日志线索、怀疑路径、验收想法
5. 同步更新 docs/ROADMAP.md「相关条目」若是中长期项
6. 向主人确认：本日新建 N 条、合并 N 条（列标题）

红线：不改交易核心代码；不删旧 REQ；密钥不入库。
```

### PM 写完整队列（18:15）

```text
你是 PM。禁止大改业务代码。

1. 先确认本地有 pm/trade_journal/今天.md；没有则 schtasks /run QuantLearn_TradeJournal
2. pm_cli list 出所有 pending/open/ready/testing
3. 写 pm/cursor_queue/今天.md：
   - 【完整列表】P0+P1+P2，不要只塞 3 条
   - 每项尽量带：md 路径、关键文件猜测、验收命令、做完改哪个状态
   - 超大项放「本周不做」但保留在文件里
4. 对前段（P0 与靠前 P1）若无 PLAN，在 pm/dev/ 写最短 PLAN
5. 企微短消息：P0x / P1x / P2x + 让主人复制 REVIEW_LOOP「Cursor 一键话术」
6. 不要自己 git push；交给 18:45 DailyGitSync。远程是否成功由 19:15 守夜验收。

红线：禁止 force push；禁止动 webhook；禁止把队列缩成「只留 P0」；禁止改交易核心代码。
```

### ★守夜验货（19:15，必开）

完整提示词见 [OPENCLAW_DAILY_RUN.md](./OPENCLAW_DAILY_RUN.md) §3 **任务 B**。摘要：

1. `git fetch` 后检查 `origin/master` 是否有今日台账+收盘摘要  
2. 没有 → 补跑 TradeJournal/DailyClose/DailyGitSync  
3. 仍没有 → 企微【量化失职】+ 写 `pm/ops/今天-nightwatch.md`

### 晚间统一推 master（18:45 + 20:30，schtasks，不占 LLM）

产机任务名：
- `QuantLearn_DailyGitSync` → 18:45（台账主班）
- `QuantLearn_DailyGitSyncEvening` → 20:30（承接 20:00 LLM 日报）  
同一 bat：`scripts/daily_git_sync_runner.bat`

只提交白名单：`pm/trade_journal`、`pm/cursor_queue`、`pm/requirements|bugs|dev|test_reports|ops`、`output/swing_daily|swing_pool|reviews`、`daily_reports/`、`docs/reviews/`、`output/pm_daily_report_*.md`、`output/daily_close_*.md`。  
**不推**：`scripts/` 交易代码、`*.db`、`config.local.yaml`。

```bat
schtasks /create /f /tn "QuantLearn_DailyGitSync" /tr "%ROOT%\scripts\daily_git_sync_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 18:45
schtasks /create /f /tn "QuantLearn_DailyGitSyncEvening" /tr "%ROOT%\scripts\daily_git_sync_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 20:30
```

手动试跑：

```bat
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
.venv\Scripts\python.exe -u scripts\daily_git_sync.py --dry-run
.venv\Scripts\python.exe -u scripts\daily_git_sync.py
```

### 20:00 LLM 各类日报（必开）

完整提示词见 [DEPLOYMENT.md](./DEPLOYMENT.md) 步骤 6 **提示词 C**。摘要：

1. 写 `daily_reports/今天-rd-report.md`（+ 可选 finance）  
2. `schtasks /run /tn QuantLearn_DailyGitSyncEvening`  
3. `git fetch` 确认远程可见；只推企微不算完成

### 理财复盘（16:30）

```text
【任务】交易复盘备注（不改成交表）。
1. 必要时跑 trade_journal.py --no-push
2. 填 pm/trade_journal/今天.md「复盘备注」
3. 发现问题 → 直接开 BUG/REQ 文件（不要只吐槽）
```

### 开发经理（18:00）

```text
对 cursor_queue 将出现的 P0 与主要 P1：写 pm/dev/PLAN-*.md
含：根因假设、改哪些路径、pytest、风险。禁止直接大改代码。
```

---

## 7. 交易轨道 vs 治理轨道

| 轨道 | 内容 | 谁 |
|------|------|-----|
| 交易 | Pulse / 扫盘 / 波段 / 台账 / 收盘 | schtasks |
| 上传 | 白名单 push master | schtasks `DailyGitSync` |
| 治理 | 入库 / 队列 / 复盘备注 | OpenClaw 18:15 |
| 修码（可选自动） | 本机 CLI 消费队列 → feature 分支 | `cursor_queue_auto_runner.sh`（人工 MR） |
| 守夜 | 验货远程有今日产物；失败补跑+告警 | OpenClaw 19:15 **必开** |

---

## 8. 成功标准

| 指标 | 健康 |
|------|------|
| 聊天里提过的缺陷是否都有 md | 是 |
| 每晚是否有完整 cursor_queue | 是（含 P1/P2） |
| **次日 `git pull` 能否看到昨台账** | **是（硬 SLO）** |
| Cursor 是否被要求「只修 P0」 | **否** |
| OpenClaw 改业务代码 | ≈ 0 |
| 19:15 守夜是否挂着 | **是** |

---

## 9. 相关文件

| 路径 | 说明 |
|------|------|
| `pm/cursor_queue/` | 每晚完整修复菜单 |
| `pm/requirements/` / `pm/bugs/` | 需求与缺陷正文 |
| `pm/dev/` | 方案草稿 |
| `scripts/cursor_queue_auto_runner.sh` | 本机可选：CLI 自动消费队列（只推 feature） |
| `scripts/pm_cli.py` | 状态 |
| `docs/DEPLOYMENT.md` | 交易怎么跑 |
