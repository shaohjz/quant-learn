# 量化项目部署与运行手册（给 OpenClaw）

> **本文唯一权威。** 主人让你部署/检查时：**只读本文并严格执行**；不要另找提示词、不要另编定时器。  
> `OPENCLAW_DAILY_RUN.md` / `CRON_JOBS.md` 等是配套细读，**缺省可只靠本文**。  
> **项目目的**：模拟验证 → **每天给人（主人）实盘挂单建议**（盘中提醒 + 收盘赚亏）。  
> **默认不代客实盘下单**（除非主人另行要求开 QMT live）。  
>  
> **产机路径（写死）**：`C:\Users\Administrator\.openclaw\workspace\quant-learn`  
> **时区**：`Asia/Shanghai`  
> **配套**（可选细读）：[OPENCLAW_DAILY_RUN.md](./OPENCLAW_DAILY_RUN.md) · [CRON_JOBS.md](./CRON_JOBS.md) · [REALTIME.md](./REALTIME.md) · [REVIEW_LOOP.md](./REVIEW_LOOP.md)  
> **更新**：2026-07-24（Cursor 最高规则：改代码必须同改本文并 push；主人只收一句话口令）  
> **给 Cursor 的铁律**：`.cursor/rules/deploy-docs-first.mdc` — 有部署影响的改动 → 更新本文 → push → 只回主人 OpenClaw 一句话。

---

## 主人怎么喊你（一句话就够）

主人只需说下面任意一句，你就执行本文 ★ 全流程：

> **读 `docs/DEPLOYMENT.md`，按文档从 ★ 做到交付报告。**

> **重新部署 quant-learn：`git pull` 后严格按 `docs/DEPLOYMENT.md` 执行。**

你就执行，**不要另编一套定时器、不要问主人要提示词**（提示词全在本文步骤 6）。  
做完写 `pm/ops/今天-deploy.md` 回复。

### 文档同步（给 Cursor / 提交者）

改了调度、runner bat、波段池、Pulse/日报/守夜入口时，**同一次提交必须改** `docs/DEPLOYMENT.md`（及必要时 `CRON_JOBS.md` / `REALTIME.md`）。  
项目已挂 Cursor hook：`git commit` 若漏改部署文档会拦截提醒。

---

# ★ 主人验收（硬 SLO，写进脑子）

| 验收项 | 截止 | 失败怎么办 |
|--------|------|------------|
| `origin/master` 有 `pm/trade_journal/交易日.md` | 当日 19:30 前 | OpenClaw 守夜补跑；仍无 → 企微【量化失职】 |
| 同日有 `output/daily_close_交易日.md` | 同上 | 同上 |
| 企微有台账/收盘或 DailyGitSync 短讯 | 当日 19:30 前 | 查 webhook + schtasks Last Result |

**上传主职** = schtasks `QuantLearn_DailyGitSync`（18:45）。  
**OpenClaw 主职** = **19:15 守夜验货**（提示词就在本文步骤 6，禁止只写「落盘即可」）。  
旧提示词「落盘即可，18:45 会推」= **失职设计，已废**。

---

# ★ OpenClaw：如何跑这个项目（必读，按顺序做）

你是 OpenClaw Agent。主人要的是：**盘中有提醒、收盘知道波段赚亏、能扫大盘找票、每天有交易台账可复盘**。  
按下面步骤执行。每步写清成功/失败。完成后写 `pm/ops/YYYY-MM-DD-deploy.md`。

## 约束（红线）

1. **禁止**用 LLM `agentTurn` 去扫盘、模拟下单、改生产交易代码并自动 merge。  
2. **禁止**把 webhook key 写进 git；放 `config.local.yaml`。  
3. **禁止**开启实盘自动下单（QMT live），除非主人明文说「开 live」。  
4. 交易/扫描类任务 **只用 Windows 任务计划（schtasks）跑 bat**；不要用 LLM cron 堆。  
5. 同一功能只留一个入口：有 `QuantLearn_SwingDaily` 就停掉 LLM「短线波段扫描」。  
6. OpenClaw **LLM cron 有个数限制** → **最多保留 1～2 条**晚间写 `pm/` 的文案任务（见步骤 6）。

## ★★ 两套定时器（必懂，别混）

| 哪套 | 命令/界面 | 干什么 | 数量 |
|------|-----------|--------|------|
| **Windows 任务计划** | `schtasks` + 「任务计划程序」GUI | **全部**交易：扫盘 / Pulse / 波段 / 台账 / 收盘摘要 | 可开多个 |
| **OpenClaw Cron** | `openclaw cron` | **最多 1～2 条** LLM 文案（入库、写 cursor_queue） | **有限额** |

- 「盘中每 10 分 / 每 30 分」= 在 **Windows GUI** 给对应 schtasks 勾「重复任务间隔」。  
- **禁止**把 Pulse/Scanner 做成 OpenClaw LLM 每 N 分钟一条（占满名额还容易挂）。  
- 细节表见 [CRON_JOBS.md](./CRON_JOBS.md)「两套定时器」。

## 步骤 0 — 进入目录并拉代码

```bat
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
git status
git pull
git log -1 --oneline
```

若目录不存在：按「第二节 环境安装」先 clone。

## 步骤 1 — Python 环境

```bat
dir .venv\Scripts\python.exe
```

没有则：

```bat
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install -e ".[research,web,dev]"
```

最低可跑（装不全时）：

```bat
.venv\Scripts\python.exe -m pip install pyyaml requests pandas numpy
```

## 步骤 2 — 企微 webhook

检查是否有真实 key（不是 `YOUR_KEY_HERE`）：

- 优先：`config.local.yaml` → `notify.wecom_webhook`  
- 其次：`config.yaml` → `notify.wecom_webhook`

没有则创建 `config.local.yaml`（勿 commit）：

```yaml
notify:
  wecom_webhook: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=主人提供的KEY'
notifier:
  wecom_webhook: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=主人提供的KEY'
```

冒烟阶段可先：

```bat
set NOTIFIER_DRY_RUN=1
```

## 步骤 3 — 初始化 DB

```bat
set QUANT_DB_PATH=C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db
.venv\Scripts\python.exe -c "from sim.db import init_tables; init_tables()"
```

账户约定（日常只盯两个）：

| id | 名字 | 用途 | 初始资金 |
|----|------|------|:--------:|
| **1** | learn | **模拟学习仓** | **10 万** |
| 2 | real_portfolio | 真仓镜像（可选，默认可不推） | 2.5 万（镜像，不在模拟 DB） |
| **3** | swing_trade | **波段模拟**（挂单建议 / 波段赚亏） | **5 万** |

### 资金真源（唯一入口）

- **`config.yaml` 的 `accounts.*` 是资金的唯一声明**（`initial_cash` / `max_total_value` / `account_name`）。
- 所有代码读资金必须走 `sim.config.get_account_config(account_id)`（或 `account_initial_cash` / `account_max_total_value`）。**禁止**再写 `'learn' if id==1 else 'real'` 或散落硬编码（历史上 2 万 / 10 万 / 20 万 / 5 万混用导致收益率鬼畜）。
- **NAV / 收益率基准以 DB.initial_cash 为准**（REQ-094，反映历史资金事件）；config 只做「声明 + 变更告警」，不自动覆盖 DB。
- 一致性自查（只读，随时可跑）：

```bat
.venv\Scripts\python.exe -u scripts\capital_status.py
```

- 要按 config 重置账户资金（清仓 + 归零 NAV）：

```bat
.venv\Scripts\python.exe -u scripts\reset_account.py            REM 重置 #1 + #3
.venv\Scripts\python.exe -u scripts\reset_account.py --only swing
```

## 步骤 4 — 冒烟（必须全绿再挂任务）

```bat
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set NOTIFIER_DRY_RUN=1

REM A 盘中脉搏（真仓阈值 + 波段盯盘 + 指数）
.venv\Scripts\python.exe -u scripts\quant_pulse.py --force --no-push

REM A2 动态稳定池（周末/休市用 --mode hist；交易日可用 auto）
.venv\Scripts\python.exe -u scripts\swing_pool_builder.py --max-pool 50 --min-score 70 --mode hist --force

REM A3 盘前波段机会文案（正式 bat 会推企微；冒烟用 --no-push）
.venv\Scripts\python.exe -u scripts\swing_auto.py --no-push --title "盘前波段扫描报告"

REM B 波段收盘链路（模拟成交 + 赚亏结论）
.venv\Scripts\python.exe -u scripts\swing_daily_report.py --no-push

REM C 交易台账
.venv\Scripts\python.exe -u scripts\trade_journal.py --no-push

REM D 双账户收盘摘要（当日盈亏必须「相对昨日净值」，禁止再出现总资产-100000 的假 +119%）
.venv\Scripts\python.exe -u scripts\daily_close_report.py --no-push

REM E 盘前大盘扫（≈800，失败会 fallback lite）
.venv\Scripts\python.exe -u scripts\scanner_with_fallback.py
```

**成功标准：**

| 检查 | 期望 |
|------|------|
| A | 退出码 0；无未捕获 traceback |
| A2 | `output\swing_pool\latest.json` 存在且 `stocks` 约几十只（方法合格+软上限50）；`data_mode` 为 hist/live |
| A3 | 打印「盘前波段扫描报告」；账户 #3；有机会则含盈亏比/建议仓位 |
| B | `output\swing_daily\今天.md` 含「波段结论」「挂单建议」 |
| C | `pm\trade_journal\今天.md` 存在 |
| D | 文案含「相对昨日净值」；**不能**再出现离谱日涨跌幅（如 +119%） |
| E | Top 或 fallback 成功 |
| DB | 有 account_id=1 与 3（B 可自动建 #3） |

任一步失败 → **先修再挂 schtasks**，把错误写进 deploy 报告。

## 步骤 5 — 挂 Windows 计划任务（交易主调度，不占 LLM）

管理员 CMD：

```bat
set ROOT=C:\Users\Administrator\.openclaw\workspace\quant-learn

REM ① 08:30 宽基选股
schtasks /create /f /tn "QuantLearn_MorningScan" /tr "%ROOT%\scripts\morning_scanner_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 08:30

REM ①b 08:40 动态稳定波段池（方法过滤+软上限50）
schtasks /create /f /tn "QuantLearn_SwingPool" /tr "%ROOT%\scripts\swing_pool_builder_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 08:40

REM ② QuantPulse：先建 09:35 一次触发，再打开 Windows「任务计划程序」GUI
REM    → QuantLearn_QuantPulse → 触发器 →「重复任务间隔」= 10 分钟，持续时间到 14:50
REM    ※ 这是 Windows 计划任务，不是 openclaw cron，不是 LLM
schtasks /create /f /tn "QuantLearn_QuantPulse" /tr "%ROOT%\scripts\quant_pulse_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 09:35

REM ③ IntradayScanner：可选。同样用 Windows GUI 设重复 30 分钟到 14:30
REM    ※ 禁止做成 OpenClaw LLM 每 30 分一条
schtasks /create /f /tn "QuantLearn_IntradayScanner" /tr "%ROOT%\scripts\intraday_scanner_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 10:00

REM ④ 16:05 波段日报
schtasks /create /f /tn "QuantLearn_SwingDaily" /tr "%ROOT%\scripts\swing_daily_report_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 16:05

REM ⑤ 16:15 交易台账
schtasks /create /f /tn "QuantLearn_TradeJournal" /tr "%ROOT%\scripts\trade_journal_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 16:15

REM ⑥ 16:20 双账户收盘摘要
schtasks /create /f /tn "QuantLearn_DailyClose" /tr "%ROOT%\scripts\daily_close_report_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 16:20

REM ⑦ 18:45 台账/PM/QA/Ops 白名单推 master（不占 LLM）
schtasks /create /f /tn "QuantLearn_DailyGitSync" /tr "%ROOT%\scripts\daily_git_sync_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 18:45

schtasks /query /fo LIST | findstr QuantLearn
```

**必开（Windows）：** MorningScan · SwingPool · QuantPulse（+GUI 10 分重复）· SwingDaily · TradeJournal · DailyClose · **DailyGitSync**

**可选（Windows）：** IntradayScanner（消息多就关）  

**勿双开：** 已开 Pulse 则关掉单独的 `PortfolioAlert` / `SwingIntraday` schtasks。

试跑：

```bat
schtasks /run /tn QuantLearn_SwingPool
schtasks /run /tn QuantLearn_QuantPulse
schtasks /run /tn QuantLearn_SwingDaily
schtasks /run /tn QuantLearn_TradeJournal
schtasks /run /tn QuantLearn_DailyClose
schtasks /run /tn QuantLearn_DailyGitSync
type %ROOT%\output\swing_pool_builder.log
type %ROOT%\output\quant_pulse.log
type %ROOT%\output\swing_daily_report.log
type %ROOT%\output\trade_journal.log
dir %ROOT%\output\swing_pool
dir %ROOT%\pm\trade_journal
dir %ROOT%\output\swing_daily
```

### 波段池说明（2026-07-24）

| 项 | 内容 |
|----|------|
| 脚本 | `scripts/swing_pool_builder.py` + `swing_auto.py`（同 bat） |
| 任务 | `QuantLearn_SwingPool` **08:40** 必开 |
| 入池规则 | **方法过滤优先**：硬条件（非ST/价位/成交额/ATR/振幅/回撤）+ `stability_score≥70`；**软上限 50**（防 Pulse 扫爆；不是死卡 Top20） |
| 底池 | 沪深300+中证500（`data/universe_cache.json`） |
| 盘前通知 | builder 后跑 `swing_auto.py` → 企微「盘前波段扫描报告」（账户 #3 + 盈亏比） |
| 盘中扫谁 | Pulse → `swing_intraday_watch` 读 `output/swing_pool/latest.json`；**提醒同时模拟买卖账户#3**；买入文案含涨跌空间/毛净盈亏比/手续费/建议仓位 |
| 立刻同步 | 模拟买卖成功 → 另发企微 **text + @all**「🚨【立刻同步实盘】…请马上挂单」；收盘补漏成交同样推 |
| 收盘 | `swing_daily_report` 再扫 + **盘中提醒补漏**（防「盘中喊买、收盘空仓」） |
| 周末 | `--mode hist`（日K）；`auto` 周末自动 hist |
| 持仓 | 账户 #3 持仓强制保留在池内 |
| 兜底 | latest 缺失 → 旧 `STOCK_POOL` 种子 |

### ★ 本次变更怎么部署（波段池扩容 + 立刻同步实盘）

产机只做下面几步即可（**不用重建全部 schtasks**，旧任务名照旧）：

```bat
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
git pull
git log -1 --oneline

REM 1) 立刻按新规则重建池（方法过滤 + 软上限50）
.venv\Scripts\python.exe -u scripts\swing_pool_builder.py --max-pool 50 --min-score 70 --mode auto --force

REM 2) 确认池子变大了（stocks 应明显 >20，一般几十只，≤50）
.venv\Scripts\python.exe -c "import json; d=json.load(open(r'output\swing_pool\latest.json',encoding='utf-8')); print(d.get('date'), 'stocks=', len(d.get('stocks',[])), 'min_score=', d.get('min_score'), 'max_pool=', d.get('max_pool'), 'selection=', d.get('selection'))"

REM 3) 确认 bat 已是新参数（pull 后应含 --max-pool 50）
findstr /C:"max-pool" scripts\swing_pool_builder_runner.bat

REM 4) 盘中链路冒烟（非交易时段加 --force；--no-push 不真发企微）
.venv\Scripts\python.exe -u scripts\swing_intraday_watch.py --force --no-push --no-trade
```

**验收：**

| 项 | 过关标准 |
|----|----------|
| 代码 | `git log -1` 含本次 commit；runner bat 有 `--max-pool 50 --min-score 70` |
| 池 | `latest.json` 的 `selection=method+cap`，`stocks` 约几十只（≤50） |
| 调度 | `QuantLearn_SwingPool` / `QuantLearn_QuantPulse` / `QuantLearn_SwingDaily` 仍启用（任务名不变，拉代码即生效） |
| 立刻同步 | 下一笔模拟买卖成功后，企微应收到两条：markdown 详情 + **text @所有人「立刻同步实盘」** |
| 企微 | `config.local.yaml` 里 `notify.wecom_webhook` 有效；别开 `NOTIFIER_DRY_RUN=1` 挡正式推送 |

**不用做：** 不用改 schtasks 创建命令；不用改账户 #3；不用动 webhook key。

## 步骤 6 — 整理 OpenClaw Cron（LLM 限量 + 提示词全文）

```bat
openclaw cron list
```

| 动作 | 对象 |
|------|------|
| **全部删/停** | 任何交易扫描、波段扫描、每 N 分钟盯盘的 **LLM agentTurn** |
| **停用（建议）** | 每日多轮「研发修复」LLM（09/18/21） |
| **必留 1 条** | **工作日 19:15 守夜** — 用下面「提示词 B」整段贴进 cron |
| **最多再留 1 条** | **工作日 18:15 治理落盘** — 用下面「提示词 A」（可与理财合并） |
| **不要** | schtasks 已跑的脚本再在 OpenClaw 挂一份（双推）；不要只写「落盘即可」却不看远程 |

可选：若不用 schtasks，交易脚本可用 OpenClaw **`systemEvent`（非 LLM）** 调 bat/python——仍算「脚本调度」，不占 LLM 名额。优先 schtasks。

### 提示词 A — 治理落盘（cron 约 18:15，可选）

把下面 **整段** 贴进 OpenClaw `agentTurn`：

```text
你是 OpenClaw 治理 Agent。工作目录：
C:\Users\Administrator\.openclaw\workspace\quant-learn
先读 docs/DEPLOYMENT.md（本文权威），再执行。

禁止：改交易核心代码；force push；提交密钥/config.local/*.db。
禁止假设「别人会推 git」——你只负责落盘；推送由 18:45 schtasks 做，
但 19:15 守夜会验收（见 DEPLOYMENT 提示词 B）。

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

### 提示词 B — ★守夜验收（cron 约 19:15，必开）

> **缺这条 = 上传失职无人管。** 必须验货 + 补跑 + 告警。

把下面 **整段** 贴进 OpenClaw `agentTurn`（工作日 19:15）：

```text
你是 OpenClaw 守夜 Agent。工作目录：
C:\Users\Administrator\.openclaw\workspace\quant-learn
时区 Asia/Shanghai。今天=本地日期。权威文档：docs/DEPLOYMENT.md。

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

允许：为达成 SLO，执行
  .venv\Scripts\python.exe -u scripts\daily_git_sync.py
禁止：git add scripts/ 或交易核心。

回复主人三行：SLO=OK/FAIL；补跑了哪些任务；远程最新 commit。
```

## 步骤 7 — 交付报告

写入 `pm/ops/YYYY-MM-DD-deploy.md`，必须包含：

1. `git log -1 --oneline`  
2. 冒烟 A～E 结果  
3. **【Windows schtasks】** `findstr QuantLearn` 原文 + Pulse 是否已在 GUI 设 10 分重复  
4. **`QuantLearn_DailyGitSync` 是否 Ready**（历史漏挂过，必写 Last Run）  
5. **【OpenClaw cron】** 最终 list 原文（应几乎无交易 LLM；**必须有 19:15 守夜**）  
6. 已停用的重复/LLM 任务名  
7. 企微是否真推测过（是/否）  
8. 守夜试跑：故意 `dir` 检查今日台账路径；`schtasks /run /tn QuantLearn_DailyGitSync` 后 `git fetch` 看远程  

报告里 **必须分开两节**写 schtasks 与 openclaw cron，禁止混在一堆。

---

# 主人每天会收到什么（你要保证这套在跑）

```
【全是 Windows schtasks，不是 OpenClaw LLM cron】
08:30            MorningScan 宽基扫
08:40            SwingPool 方法过滤池≤50 + 盘前波段扫描推企微
09:35~14:50 /10m QuantPulse（GUI 设重复）真仓阈值+波段(扫池)+指数
10:00~14:30 /30m IntradayScanner（可选，GUI 设重复）
16:05            SwingDaily 波段赚亏+挂单建议
16:15            TradeJournal 台账
16:20            DailyClose 双账户摘要
18:45            DailyGitSync 台账/PM/QA/Ops → push master   ★上传主职

【OpenClaw LLM】
18:15 左右        需求入库 + 写 pm/cursor_queue（可合并成一条）
19:15            ★守夜验收：远程有今日台账？没有 → 补跑 + 企微【量化失职】
```
详情：本文日程表 · [REALTIME.md](./REALTIME.md) · [REVIEW_LOOP.md](./REVIEW_LOOP.md)

**本系统默认：提醒 + 模拟；挂单由主人在券商软件自己下。**

---

# 环境安装（机器上还没有项目时）

## 依赖

| 项 | 要求 |
|----|------|
| OS | Windows 10/11 |
| Python | 3.11 推荐（`>=3.11,<3.14`） |
| Git | 能拉工蜂 |
| QMT | 可选 |
| 企微机器人 | webhook |

## Clone

```bat
cd C:\Users\Administrator\.openclaw\workspace
git clone git@git.woa.com:jizhouhu/quant-learn.git
cd quant-learn
```

然后从「步骤 1」做起。

---

# 配置要点

```yaml
# config.yaml / config.local.yaml
fees:
  commission_rate: 0.00025
  min_commission: 5.0
  stamp_tax_rate: 0.0005
notify:
  wecom_webhook: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...'
```

真仓阈值在 `config.yaml`：

- `real_portfolio_rules` — 持仓止损/止盈/买区  
- `watchlist.user_manual` / `auto_discovered` — 观察股  

`portfolio_alert` / `quant_pulse` 读这些规则推送。

所有 `scripts\*_runner.bat` 写死项目路径；换机必须改 bat 或对齐路径。

---

# 日常运维（OpenClaw 心跳 / 19:15 守夜必须做）

交易日抽查（完整动作 = 本文步骤 6「提示词 B」）：

```bat
schtasks /query /tn QuantLearn_QuantPulse /v /fo LIST
schtasks /query /tn QuantLearn_TradeJournal /v /fo LIST
schtasks /query /tn QuantLearn_DailyGitSync /v /fo LIST
dir pm\trade_journal
dir output\daily_close_*.md
dir output\swing_daily
type output\daily_git_sync.log
git fetch origin
git log -1 --oneline origin/master
```

异常时优先查：本文故障排查 · [REALTIME.md](./REALTIME.md)。

---

# 故障排查

| 现象 | 处理 |
|------|------|
| **git 里没有昨天/今天台账** | **先查这张表**：①产机是否睡眠 ②`TradeJournal`/`DailyClose` Last Run ③`DailyGitSync` Last Result ④`type output\daily_git_sync.log` ⑤立刻 `/run` 补推；OpenClaw 守夜本应已告警 |
| 企微没消息 | key / `delivery.mode` / `NOTIFIER_DRY_RUN` |
| 早盘扫超时 | 正常走 `scanner_with_fallback` → lite；查网络/Zscaler |
| bat Result:1 | `cmd /k` 手动跑 bat；看对应 `output\*.log` |
| 波段赚亏永远 0 | 看 `sim_trades` account_id=3；机会分是否从未成交 |
| 盘中完全没提醒 | 查 `QuantLearn_QuantPulse` 是否启用+重复间隔；日志 `quant_pulse.log`；持续时间是否到 **14:50**（误设 4h 会在 13:35 掐断） |
| 波段池一直是旧蓝筹 | 查 `QuantLearn_SwingPool`；看 `output\swing_pool\latest.json` 日期；周末用 `--mode hist` |
| LLM cron error | 交易改 schtasks；别依赖模型在线 |
| Agent「说做了」但远程没有 | 旧提示词只落盘不验收；**补挂 19:15 守夜**，重贴本文步骤 6「提示词 B」 |

---

# 给 OpenClaw 的一键口令（主人复制即用）

主人 **只发下面这一句**（细节全在本文，不要另贴长提示）：

```text
读 docs/DEPLOYMENT.md，git pull 后严格按文档从 ★ 做到步骤 7 交付报告。
重点：DailyGitSync(18:45) + 19:15 守夜（本文步骤 6 提示词 B）+ 波段池软上限50/立刻@all同步。
缺 7/23、7/24 台账就立刻补跑 TradeJournal/DailyClose/DailyGitSync。
做完写 pm/ops/今天-deploy.md。
```

---

# 相关文档

| 文档 | 用途 |
|------|------|
| **本文 DEPLOYMENT.md** | **唯一权威：部署 + 日程 + 守夜提示词** |
| [OPENCLAW_DAILY_RUN.md](./OPENCLAW_DAILY_RUN.md) | 可选细读（与本文重复处以本文为准） |
| [REVIEW_LOOP.md](./REVIEW_LOOP.md) | 每日复盘 / 多角色 / Cursor 队列 |
| [REALTIME.md](./REALTIME.md) | 实时监控全景 |
| [CRON_JOBS.md](./CRON_JOBS.md) | 全量任务表 |
| [ROADMAP.md](./ROADMAP.md) | 需求与缺陷 |
| [qmt_integration.md](./qmt_integration.md) | QMT（可选） |
| [wecom_webhook_setup.md](./wecom_webhook_setup.md) | 企微 |
