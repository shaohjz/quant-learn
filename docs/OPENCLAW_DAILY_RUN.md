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

【OpenClaw LLM — 最多 2～3 条】
16:30            理财：填台账「复盘备注」；有问题开 BUG/REQ（可并进 18:15）
17:00~18:15      需求/PM/QA/开发经理：入库 + 写 cursor_queue（建议合并成 18:15 一条）
19:15            ★守夜：验收今日台账已进 origin/master；缺则补跑+企微告警（必开）

【Windows schtasks — 推 master】
18:45            DailyGitSync → 白名单 commit + push origin/master
```

> **硬 SLO（主人验收）**：每个交易日 **次日 00:00 前**，`origin/master` 必须能看到  
> `pm/trade_journal/昨天.md` + `output/daily_close_昨天.md`（或当日 `chore(daily)` 提交）。  
> 缺任一 = **部署失败 / Agent 失职**，不是「可选项」。

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
| **必留 1 条** | **19:15 守夜验收**（§3 任务 B）——缺这条 = 上传失职无人管 |
| **最多再 1～2 条** | 晚间：入库 + 写 `pm/cursor_queue`（建议 **18:15 一条合并**） |
| **不要** | schtasks 已跑的脚本再挂一份 LLM（双推）；不要只写「落盘即可」却不验收远程 |

### 推荐 LLM 任务 A：治理落盘（约 18:15）

把下面整段贴进 OpenClaw cron `agentTurn`：

```text
你是 OpenClaw 治理 Agent。工作目录：
C:\Users\Administrator\.openclaw\workspace\quant-learn
先读 docs/OPENCLAW_DAILY_RUN.md 与 docs/REVIEW_LOOP.md，再执行。

禁止：改交易核心代码；force push；提交密钥/config.local/*.db。
禁止假设「别人会推 git」——你只负责落盘；推送由 18:45 schtasks 做，
但 19:15 守夜任务会验收（见同文档「任务 B」）。

今日必须落盘（没有就创建）：
1) 确认本地已有（没有则立刻 schtasks /run）：
   - QuantLearn_TradeJournal → pm/trade_journal/今天.md
   - QuantLearn_DailyClose → output/daily_close_今天.md
   - QuantLearn_SwingDaily → output/swing_daily/今天.md
2) 读台账；若「复盘备注」空，补短备注（做对/做错/明日关注）。
3) 扫 output/ / 台账 / 日志，问题入库 pm/bugs 或 pm/requirements（可用 pm_cli）。
4) PM：写完整 pm/cursor_queue/今天.md（P0+P1+P2 全量）。
5) 企微短摘要：P0x/P1x/P2x + Cursor 话术提醒。

不要自己 git push（交给 18:45 DailyGitSync）。
回复列出：本地新建/更新了哪些路径；三项 schtasks 产物是否存在。
```

### 推荐 LLM 任务 B：★守夜验收（约 19:15，必开）

> **这是修复「Agent 不履行职能」的关键提示词。**  
> 旧提示词只写「落盘即可，18:45 会推」→ schtasks 挂了也没人管。守夜必须 **验货+补跑+告警**。

```text
你是 OpenClaw 守夜 Agent。工作目录：
C:\Users\Administrator\.openclaw\workspace\quant-learn
时区 Asia/Shanghai。今天=本地日期。先读 docs/OPENCLAW_DAILY_RUN.md §6/§7。

目标（硬 SLO）：origin/master 上必须有今日台账与收盘摘要。
禁止：force push；改交易核心代码；提交 *.db / config.local。

按顺序做，每步记录原文：

1) git fetch origin
   git log -1 --oneline origin/master
   git ls-tree -r --name-only origin/master | findstr /C:"pm/trade_journal/今天" /C:"daily_close_今天"
   （把「今天」换成真实 YYYY-MM-DD）

2) 若远程已有今日 trade_journal + daily_close → 写 pm/ops/今天-nightwatch.md
   「SLO OK」+ 最新 commit，结束。

3) 若远程没有：
   a. dir 本地 pm\trade_journal\今天.md 与 output\daily_close_今天.md
   b. 本地没有 → schtasks /run 依次：
      QuantLearn_TradeJournal / QuantLearn_DailyClose / QuantLearn_SwingDaily
      等 30s 再 dir 一次
   c. 本地有或补跑后 → schtasks /run /tn QuantLearn_DailyGitSync
      type output\daily_git_sync.log（看尾部）
   d. 再 git fetch；确认 origin/master 出现今日文件或 chore(daily) 提交

4) 仍失败 → 企微告警（用现有 webhook / 通知脚本），标题：
   「【量化失职】今日台账未进 master」
   正文含：schtasks Last Run 原文、daily_git_sync.log 尾 30 行、git status -sb
   并写 pm/ops/今天-nightwatch.md + pm/bugs/BUG-上传失败-日期.md

5) 额外健康抽查（失败只记 ops，不阻断）：
   schtasks /query /tn QuantLearn_DailyGitSync /v /fo LIST
   schtasks /query /tn QuantLearn_TradeJournal /v /fo LIST
   （看 Last Run Time / Last Result；Result≠0 记入 ops）

允许：为达成 SLO，对白名单路径执行
  .venv\Scripts\python.exe -u scripts\daily_git_sync.py
（这是脚本推送，不是乱改代码。）
禁止：git add scripts/ 或交易核心。

回复主人三行：SLO=OK/FAIL；补跑了哪些任务；远程最新 commit。
```

理财单独短任务（可选 16:30，也可并进任务 A）：

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

## 6. 每日自检（OpenClaw **必须**做，不是可选）

> 旧文写「可在心跳时做」→ Agent 经常跳过。现改为：**交易日 19:15 守夜必跑**（见 §3 任务 B）；  
> 心跳若开启，也应跑同一套检查。

```bat
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
git fetch origin
git log -1 --oneline origin/master
schtasks /query /fo LIST | findstr QuantLearn
dir pm\trade_journal
dir output\daily_close_*.md
type output\daily_git_sync.log
openclaw cron list
```

健康标准：

| 项 | 期望 |
|----|------|
| QuantLearn_TradeJournal | Ready；**本地**当日 `pm/trade_journal/YYYY-MM-DD.md` 存在 |
| QuantLearn_DailyClose | Ready；**本地**当日 `output/daily_close_YYYY-MM-DD.md` 存在 |
| QuantLearn_DailyGitSync | Ready；`output\daily_git_sync.log` 无 push 失败；**远程**有当日台账 |
| OpenClaw 交易 LLM cron | **0 条** |
| OpenClaw 文案 LLM | **≤2 条落盘 + 1 条 19:15 守夜**（守夜可算第 3 条） |
| cursor_queue | 交易日晚间有「今天」文件（守夜不替代，但可缺省告警） |

异常写入：`pm/ops/YYYY-MM-DD-nightwatch.md`（命令原文 + SLO OK/FAIL）。

---

## 7. 为什么「提示词看起来对、还是不上传」（根因备忘）

| 误解 | 真相 |
|------|------|
| OpenClaw Agent 负责 push master | **否**。push 是 `QuantLearn_DailyGitSync` schtasks |
| 写了 18:15「落盘即可」就够 | **不够**。落盘只写本地；schtasks 挂了远程永远没有 |
| 心跳会自动发现 | **不会**。旧文档把自检写成可选；`HEARTBEAT` 空则跳过 |
| 没 cursor_queue = 没上传 | **不一定**。台账/收盘是 schtasks；两者都缺 = 产机任务链死了 |

**正确分工**：schtasks 生产+推送；OpenClaw **守夜验收**；失败则补跑/告警。

---

## 8. 产机异常：ahead / scripts 脏（OpenClaw 照做）

自检时若出现下面两类，**分开处理**，不要混进 DailyGitSync。

### 8.1 `Your branch is ahead of origin/master by N commits`

含义：产机本地有 **已 commit 未 push** 的提交（常发生在 merge/`git pull` 后只落盘没推）。

先看是什么：

```bat
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
git status -sb
git log --oneline origin/master..HEAD
git diff --stat origin/master..HEAD
```

| 提交内容 | OpenClaw 动作 |
|----------|----------------|
| **只有** `pm/`、`output/swing_*`、台账、ops 等白名单 | 可执行：`git push origin master`（禁止 `--force`） |
| 含 `scripts/`、`vqlearn/`、`config.yaml`、交易核心 | **不要 push**；写 `pm/ops/今天-openclaw-check.md` + `pm/cursor_queue` 条目，等主人/Cursor |
| 说不清 / 有冲突风险 | **不要 push**；原文贴进 ops 报告，问主人 |

白名单 push 成功后再：

```bat
git status -sb
git log -1 --oneline
```

期望：`## master...origin/master`（无 ahead）。

### 8.2 `scripts/` 有未提交改动（如 `daily_review.py`、`pm_report.py`）

含义：业务代码脏工作区。**DailyGitSync 故意不推这些。**

OpenClaw **禁止**：

- `git add scripts/`
- 擅自 commit / push 交易或复盘脚本
- 为「变干净」而 `git checkout --` 丢掉主人可能要的改动（除非主人明文说丢弃）

OpenClaw **必须**：

1. 记录 diff 摘要（不要贴密钥）：

```bat
git status -sb
git diff --stat -- scripts/
git diff -- scripts/daily_review.py scripts/pm_report.py
```

2. 写入 `pm/ops/YYYY-MM-DD-openclaw-check.md`（路径 + `git diff --stat` 原文）  
3. 在 `pm/cursor_queue/今天.md` 加一条 **P1**：`产机 scripts 脏：daily_review.py / pm_report.py — 需 Cursor 审阅后提交或丢弃`  
4. 回复主人：**「scripts 改动留给 Cursor；我只处理了 pm/ 与推送诊断」**

主人在 Cursor 侧（本开发机或连产机）处理完后，产机再：

```bat
git pull --ff-only origin master
```

### 8.3 给主人的固定回复模板（OpenClaw 用）

```text
【产机 git】
- ahead N：已列出 origin/master..HEAD；[已 push 白名单 / 含代码未 push，等 Cursor]
- scripts 脏：[文件列表]；已写入 pm/ops/… 与 cursor_queue；未擅自提交代码
【下一步】主人/Cursor 处理 scripts 后产机 git pull
```

---

## 9. 一句话给主人

> 交易靠 Windows 任务计划；18:45 `DailyGitSync` 负责上传；OpenClaw **19:15 守夜验货**，缺台账就补跑+告警。  
> 产机 ahead 只推白名单；`scripts/` 脏一律交 Cursor。  
> 主人验收：次日 `git pull` 必须看到昨天 `pm/trade_journal/`。

完。
