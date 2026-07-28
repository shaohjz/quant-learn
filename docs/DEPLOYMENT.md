# 量化项目部署与运行手册（给 OpenClaw）

> **本文唯一权威。** 主人让你部署/检查时：**只读本文并严格执行**；不要另找提示词、不要另编定时器。  
> `OPENCLAW_DAILY_RUN.md` / `CRON_JOBS.md` 等是配套细读，**缺省可只靠本文**。  
> **项目目的**：模拟验证 → **每天给人（主人）实盘挂单建议**（盘中提醒 + 收盘赚亏）。  
> **默认不代客实盘下单**（除非主人另行要求开 QMT live）。  
>  
> **产机路径（写死）**：`C:\Users\Administrator\.openclaw\workspace\quant-learn`  
> **时区**：`Asia/Shanghai`  
> **配套**（可选细读）：[OPENCLAW_DAILY_RUN.md](./OPENCLAW_DAILY_RUN.md) · [CRON_JOBS.md](./CRON_JOBS.md) · [REALTIME.md](./REALTIME.md) · [REVIEW_LOOP.md](./REVIEW_LOOP.md)  
> **更新**：2026-07-28（PM 任务迁 markdown；止损/buy_zone/NAV 等交易修复）  
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
| `origin/master` 有 `daily_reports/交易日-*-report.md`（LLM 日报） | 当日 **21:00** 前 | 20:00 写完后跑 Evening sync；仍无 → 企微【量化失职-日报未入库】 |

**上传主职** = schtasks `QuantLearn_DailyGitSync`（**18:45** 台账）+ `QuantLearn_DailyGitSyncEvening`（**20:30** LLM 日报）。  
**OpenClaw 主职** = **19:15 守夜验货**（提示词 B）+ **20:00 各类日报必须落盘**（提示词 C）。  
旧提示词「落盘即可，18:45 会推」= **失职设计，已废**（18:45 赶不上 20:00 写的日报）。

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

REM ⑧ 20:30 再推一次 —— 承接 20:00 LLM 各类日报（同 bat，必开）
schtasks /create /f /tn "QuantLearn_DailyGitSyncEvening" /tr "%ROOT%\scripts\daily_git_sync_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 20:30

REM ⑨ REQ-100：影子信号（无 --auto-trade，只观察+shadow，不与 Pulse 双线下单）
schtasks /create /f /tn "QuantLearn_VqlearnLive" /tr "%ROOT%\scripts\vqlearn_live_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 09:25

schtasks /query /fo LIST | findstr QuantLearn
```

**必开（Windows）：** MorningScan · SwingPool · QuantPulse（+GUI 10 分重复）· SwingDaily · TradeJournal · DailyClose · **DailyGitSync(18:45)** · **DailyGitSyncEvening(20:30)** · **VqlearnLive(09:25，shadow 专用，无 auto-trade)**

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
schtasks /run /tn QuantLearn_DailyGitSyncEvening
type %ROOT%\output\swing_pool_builder.log
type %ROOT%\output\quant_pulse.log
type %ROOT%\output\swing_daily_report.log
type %ROOT%\output\trade_journal.log
type %ROOT%\output\daily_git_sync.log
dir %ROOT%\output\swing_pool
dir %ROOT%\pm\trade_journal
dir %ROOT%\output\swing_daily
dir %ROOT%\daily_reports
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

### ★ 本次变更怎么部署（赚钱闸 + 理财师日报落盘）

> **唯一目标：赚钱。** 把已有但未接入的风控接进 `sim_executor`，收紧日新建仓，理财师报告改脚本落盘（不再依赖 OpenClaw Write）。

```bat
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
git pull
git log -1 --oneline

REM 1) 确认赚钱闸配置
findstr /C:"max_daily_new_positions" /C:"max_position_pct" /C:"market_panic_enabled" config.yaml

REM 2) 冒烟：单票仓位裁剪 + 弱势熔断单元测（可选）
.venv\Scripts\python.exe -m pytest tests\test_money_gates_position_cap.py -q

REM 3) 校准观察池 buy_zone（防脏 trigger）
.venv\Scripts\python.exe -u scripts\daily_recalibrate.py

REM 4) 清已破止损残留（有则清）
.venv\Scripts\python.exe -u scripts\force_clear_breached_stops.py

REM 5) 挂/重建理财师 schtasks（15:35，脚本写 daily_reports/*-finance-report.md）
set ROOT=C:\Users\Administrator\.openclaw\workspace\quant-learn
schtasks /create /f /tn "QuantLearn_FinanceManager" /tr "%ROOT%\scripts\finance_manager_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 15:35
schtasks /run /tn QuantLearn_FinanceManager
timeout /t 20
dir daily_reports\*-finance-report.md
```

**验收：**

| 项 | 过关标准 |
|----|----------|
| 配置 | `max_daily_new_positions=1`，`max_position_pct=0.15`，`market_panic_enabled=true` |
| 执行器 | 日志可见 `弱势日禁买` / `单票仓位` / `浮亏不加仓` 拦截字样（有信号时） |
| 理财师 | `daily_reports/今天-finance-report.md` 存在；`QuantLearn_FinanceManager` Ready@15:35 |
| 旧残留 | 破止损持仓已清或记录在 ops |

**不用做：** 不必为理财师再贴 OpenClaw 长提示词写文件；脚本已双写 `daily_reports/` + `output/finance_manager/`。

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

**不用做（波段池那次）：** 不用改账户 #3；不用动 webhook key。

### ★ 本次变更怎么部署（LLM 日报进 Git：20:30 Evening sync）

> **问题**：18:45 DailyGitSync 早于 20:00 LLM 日报 → 日报只在产机本地，Git 经常缺。  
> **解法**：再建一条 **20:30** 同 bat 任务 + 提示词 C 强制落盘 `daily_reports/`。

```bat
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
git pull
git log -1 --oneline

REM ★必须新建（旧机只有 18:45 那条不够）
set ROOT=C:\Users\Administrator\.openclaw\workspace\quant-learn
schtasks /create /f /tn "QuantLearn_DailyGitSyncEvening" /tr "%ROOT%\scripts\daily_git_sync_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 20:30

schtasks /query /tn QuantLearn_DailyGitSync /v /fo LIST
schtasks /query /tn QuantLearn_DailyGitSyncEvening /v /fo LIST

REM 冒烟：手动跑晚班（无新文件时会「无白名单变更，跳过」也算过）
schtasks /run /tn QuantLearn_DailyGitSyncEvening
timeout /t 15
type output\daily_git_sync.log
```

**OpenClaw cron：** 保留/新建工作日 **20:00** 日报任务，提示词换成本文 **提示词 C**（可 1 条合并 PM+研发+理财，也可多条但每条必须落盘）。

**验收：**

| 项 | 过关标准 |
|----|----------|
| schtasks | `DailyGitSync` Ready@18:45 + `DailyGitSyncEvening` Ready@20:30 |
| cron | 有 20:00 日报（提示词含 `daily_reports/` + 写完可 `/run Evening`） |
| 白名单 | `daily_reports/`、`output/reviews/`、`docs/reviews/`、`output/pm_daily_report_*.md` 可被 sync |
| 下一交易日 21:00 | `git ls-tree origin/master` 能看到当日 `daily_reports/*-report.md` |

**DailyGitSync 行为要点（`scripts/daily_git_sync.py`）：**

- 成功 / 失败会推企微 markdown 摘要（文件分类统计）；**无变更「跳过」默认不推**（防 18:45+20:30 双空刷屏）。需要跳过也通知时加 `--notify-skip`。
- `--no-notify` 关闭企微；`--dry-run` 不推也不拿锁。
- 跨平台排他锁：`output/.daily_git_sync.lock`（mkdir），防双班重叠；超时约 120s 退出码 3。
- 白名单含 `daily_reports/`、`output/finance_manager/`、`docs/reviews/`、`output/pm_daily_report_*.md` 等。
- **2026-07-28**：`git pull --rebase --autostash`（产机 scripts/ 脏区不再卡死 push）；子进程统一 `encoding=utf-8, errors=replace`；push 失败日志打印 `PUSH FAILED`；pull 仍失败时会兜底尝试 push。

```bat
.venv\Scripts\python.exe -u scripts\daily_git_sync.py --dry-run
.venv\Scripts\python.exe -u scripts\daily_git_sync.py --no-notify
```

### 2026-07-28 交易修复（git pull 后立刻生效）

| 修复 | 文件 | 产机动作 |
|------|------|----------|
| **REQ-105 buy_zone 脏阈值** | `daily_recalibrate.py` 展开嵌套观察池；`sim_executor` trigger vs 实时 MA10 拦截 | **必跑**：`.venv\Scripts\python.exe -u scripts\daily_recalibrate.py` |
| **REQ-099/101 止损残留** | confirmed 止损 → `SELL_ALL`；半仓不足一手升级清仓 | 下一轮 Pulse 自动清；或立刻：`.venv\Scripts\python.exe -u scripts\force_clear_breached_stops.py --dry-run` 再去掉 `--dry-run` |
| **REQ-069/071 NAV** | 买入只扣 cash，`total=cash+Σmv`；收盘快照矫正 `sim_account` | pull 后次日收盘即可；盘中可跑 `daily_close_report.py --no-push` |
| **REQ-048 残留假 executed** | `portfolio_alert` armed 路径改看 `trade is not None` | pull 即可 |
| **REQ-100 影子/刷价** | 重建 `QuantLearn_VqlearnLive`（无 auto-trade）；`swing_daily` 先刷价再扫池 | **必建** schtasks ⑨；见上 |
| **DailyGitSync 脏区** | `--autostash` + utf-8 | pull 后下次 18:45 自动 push |

残留止血（明日开盘前可先 dry-run）：

```bat
.venv\Scripts\python.exe -u scripts\force_clear_breached_stops.py --dry-run
.venv\Scripts\python.exe -u scripts\force_clear_breached_stops.py --codes 000725,300017,300146
```
## 步骤 6 — 整理 OpenClaw Cron（LLM 限量 + 提示词全文）

```bat
openclaw cron list
```

| 动作 | 对象 |
|------|------|
| **全部删/停** | 任何交易扫描、波段扫描、每 N 分钟盯盘的 **LLM agentTurn** |
| **停用（建议）** | 每日多轮「研发修复」LLM（09/18/21） |
| **必留 1 条** | **工作日 19:15 守夜** — 用下面「提示词 B」整段贴进 cron |
| **必留 ≥1 条** | **工作日 20:00 各类日报落盘** — 用下面「提示词 C」（PM/研发/理财可合并成 1 条） |
| **最多再留 1 条** | **工作日 18:15 治理落盘** — 用下面「提示词 A」 |
| **不要** | schtasks 已跑的脚本再在 OpenClaw 挂一份（双推）；不要只写「落盘即可」却不看远程；**不要假设 18:45 会推走 20:00 才写的文件** |

可选：若不用 schtasks，交易脚本可用 OpenClaw **`systemEvent`（非 LLM）** 调 bat/python——仍算「脚本调度」，不占 LLM 名额。优先 schtasks。

### 提示词 A — 治理落盘（cron 约 18:15，可选）

把下面 **整段** 贴进 OpenClaw `agentTurn`：

```text
你是 OpenClaw 治理 Agent。工作目录：
C:\Users\Administrator\.openclaw\workspace\quant-learn
先读 docs/DEPLOYMENT.md（本文权威），再执行。

禁止：改交易核心代码；force push；提交密钥/config.local/*.db。
禁止写 data/pm.db 任务（已废除）。新需求用：
  .venv\Scripts\python.exe scripts\pm_cli.py create bug "标题" --priority P0
或直接在 pm/requirements|bugs 新建带 YAML frontmatter 的 md。
禁止假设「别人会推 git」——你只负责落盘；台账由 18:45 DailyGitSync 推，
LLM 日报由 20:30 DailyGitSyncEvening 推；19:15 守夜验台账（提示词 B）。

今日必须落盘（没有就创建）：
1) 确认本地已有（没有则立刻 schtasks /run）：
   - QuantLearn_TradeJournal → pm/trade_journal/今天.md
   - QuantLearn_DailyClose → output/daily_close_今天.md
   - QuantLearn_SwingDaily → output/swing_daily/今天.md
2) 读台账；若「复盘备注」空，补短备注（做对/做错/明日关注）。
3) 扫 output/ / 台账 / 日志，问题入库 pm/bugs 或 pm/requirements（可用 pm_cli）。
4) PM：写完整 pm/cursor_queue/今天.md（P0+P1+P2 全量）。
5) 企微短摘要：P0x/P1x/P2x + Cursor 话术提醒。

不要自己 git push（交给 18:45 / 20:30 schtasks）。
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

### 提示词 C — ★20:00 各类日报落盘（必开，可合并成 1 条）

> **缺这条 = 企微有日报、Git 永远没有。** 只推企微不算完成；必须写文件。  
> 现有 `pm-agent-daily-report` / `理财师-每日复盘汇报` 等 20:00 cron：**提示词改成本段**（或多条各自落盘，路径统一）。

把下面 **整段** 贴进 OpenClaw `agentTurn`（工作日 **20:00**）：

```text
你是 OpenClaw 日报 Agent。工作目录：
C:\Users\Administrator\.openclaw\workspace\quant-learn
时区 Asia/Shanghai。今天=本地日期 YYYY-MM-DD。权威：docs/DEPLOYMENT.md。

目标：把今日各类 LLM 日报写入仓库白名单路径，让 20:30 DailyGitSyncEvening 能推进 origin/master。
禁止：force push；改交易核心；提交 *.db / config.local；只发企微不写文件；**禁止写 pm.db 任务**。
任务状态改 pm/requirements|bugs 的 md frontmatter，或 `pm_cli.py update`。

必须落盘（UTF-8 markdown，覆盖写今日文件即可）：
1) daily_reports/今天-rd-report.md
   — 研发/PM 视角：代码变更摘要、PM 队列 P0/P1/testing、阻塞项、模拟盘快照、明日优先
2) daily_reports/今天-finance-report.md
   — 理财师视角：#1+#3 盈亏、持仓风险、止损/挂单建议（若本 cron 不做理财，可省略本文件，但须在回复写明「理财 cron 另写」）
可选兼容路径（旧脚本）：output/reviews/今天.md 、 docs/reviews/今天.md 、 output/pm_daily_report_今天.md
（白名单已含；优先仍用 daily_reports/）

写完立刻：
  schtasks /run /tn QuantLearn_DailyGitSyncEvening
  （若任务不存在 → schtasks /run /tn QuantLearn_DailyGitSync）
等 20s：type output\daily_git_sync.log（看尾部）
再：
  git fetch origin
  git ls-tree -r --name-only origin/master | findstr daily_reports\今天
若远程仍没有今日 daily_reports → 再跑一次 sync；仍失败写 pm/ops/今天-report-sync-fail.md 并企微【量化失职-日报未入库】。

企微可发精简版，但文件必须先写好。
回复主人：写了哪些路径；Evening sync 是否跑；远程是否可见。
```

## 步骤 7 — 交付报告

写入 `pm/ops/YYYY-MM-DD-deploy.md`，必须包含：

1. `git log -1 --oneline`  
2. 冒烟 A～E 结果  
3. **【Windows schtasks】** `findstr QuantLearn` 原文 + Pulse 是否已在 GUI 设 10 分重复  
4. **`QuantLearn_DailyGitSync`(18:45) + `QuantLearn_DailyGitSyncEvening`(20:30) 是否 Ready**（历史漏挂过，必写 Last Run）  
5. **【OpenClaw cron】** 最终 list 原文（应几乎无交易 LLM；**必须有 19:15 守夜 + 20:00 日报/提示词 C**）  
6. 已停用的重复/LLM 任务名  
7. 企微是否真推测过（是/否）  
8. 守夜试跑：故意 `dir` 检查今日台账路径；`schtasks /run /tn QuantLearn_DailyGitSync` 后 `git fetch` 看远程  
9. 日报链路：`dir daily_reports`；试跑 `DailyGitSyncEvening`；确认白名单含 `daily_reports/`  

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
15:35            FinanceManager 理财师日报→daily_reports/*-finance-report.md
18:45            DailyGitSync 台账/PM/QA/Ops → push master   ★上传主班
20:30            DailyGitSyncEvening 同 bat → 推 LLM 日报   ★上传晚班

【OpenClaw LLM】
18:15 左右        需求入库 + 写 pm/cursor_queue（可合并成一条）
19:15            ★守夜验收：远程有今日台账？没有 → 补跑 + 企微【量化失职】
20:00            ★各类日报落盘 daily_reports/（提示词 C）→ 企微精简版

【本机 Linux 可选 · 非产机】
19:30 左右        cursor_queue_auto_runner.sh 消费队列 → 只推 feature 分支（人工 MR）
```
详情：本文日程表 · [REALTIME.md](./REALTIME.md) · [REVIEW_LOOP.md](./REVIEW_LOOP.md) · 下文「本机 Cursor 队列自动消费」

**本系统默认：提醒 + 模拟；挂单由主人在券商软件自己下。**

---

# 本机 Cursor 队列自动消费（可选增强 · 方案 A）

> **与产机 OpenClaw 职责分开。** 产机继续：18:15 写 `pm/cursor_queue` → 18:45 DailyGitSync 推 master。  
> **本机**（开发 Linux）可选：用 Cursor Agent CLI 无头消费队列，**只推 feature 分支**，人工验收 MR。  
> **默认绝不自动推 master。** 未装 CLI / 无 `CURSOR_API_KEY` 时脚本优雅退出并提示，不影响产机。

## 谁跑 / 谁不跑

| 角色 | 做什么 |
|------|--------|
| 产机 OpenClaw + schtasks | 写队列、推白名单到 master、守夜 — **不变** |
| 本机 `scripts/cursor_queue_auto_runner.sh` | 拉 master → 开 `feat/cursor-auto-YYYYMMDD` → `agent -p --force` → **有新 commit 才** push **feature** → 可选建 MR → 切回 master |
| 主人 | 验收 MR / 合并；也可继续手动画「Cursor 一键话术」 |

## 安装 Cursor Agent CLI（本机）

```bash
curl https://cursor.com/install -fsS | bash
export PATH="$HOME/.local/bin:$PATH"
agent --version
# 认证二选一：
export CURSOR_API_KEY=你的key    # 或
agent login
```

文档：https://cursor.com/docs/cli/installation

## 冒烟

```bash
cd /path/to/quant-learn
# 演练（不调 agent、不 push）
CURSOR_AUTO_DRY_RUN=1 ./scripts/cursor_queue_auto_runner.sh
# 真跑（默认最多 1 项）
export CURSOR_API_KEY=...
CURSOR_AUTO_MAX_ITEMS=1 ./scripts/cursor_queue_auto_runner.sh
# 日志：output/cursor_queue_auto.log（gitignore）
# 摘要：pm/ops/今天-cursor-auto.md（DailyGitSync 白名单已含 pm/ops/）
```

## 示例 crontab（本机 Linux，不是产机 schtasks）

```cron
# 交易日 19:30：等 18:45 DailyGitSync 把 cursor_queue 推进 master 后再消费
30 19 * * 1-5  cd /data/shaohjz/quant-learn && \
  CURSOR_API_KEY=*** ./scripts/cursor_queue_auto_runner.sh >> output/cursor_queue_auto.log 2>&1
```

## 安全红线

1. **只** `git push -u origin HEAD` 到 `feat/cursor-auto-*`；脚本若检测到当前在 `master`/`main` 会拒绝 push。  
2. 禁止 force push；禁止改 `config.local*` / `*.db` / 密钥。  
3. `CURSOR_AUTO_MAX_ITEMS` 默认 `1`，防一次改爆。  
4. 无 `glab` / 工蜂 token 时只 push 分支，ops 日志写「请人工开 MR」。  
5. **产机无需新建 schtasks**；知晓即可，`git pull` 后文档同步。  
6. **无产出不 push**：相对 master 无新 commit 且工作区干净 → 记 ops 后 exit 0，不 push 空分支。  
7. **并发锁**：`output/.cursor_queue_auto.lock`（mkdir）；另一实例在跑则跳过。  
8. 成功/空跑后尽量 `checkout master` + `pull --ff-only`（失败只告警）。

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

# 日常运维（OpenClaw 心跳 / 19:15 守夜 / 20:30 Evening 必须做）

交易日抽查（完整动作 = 本文步骤 6「提示词 B」+「提示词 C」）：

```bat
schtasks /query /tn QuantLearn_QuantPulse /v /fo LIST
schtasks /query /tn QuantLearn_TradeJournal /v /fo LIST
schtasks /query /tn QuantLearn_DailyGitSync /v /fo LIST
schtasks /query /tn QuantLearn_DailyGitSyncEvening /v /fo LIST
dir pm\trade_journal
dir output\daily_close_*.md
dir output\swing_daily
dir daily_reports
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
| **git 里没有 LLM 日报（daily_reports）** | ①20:00 cron 是否写了文件 `dir daily_reports` ②是否挂了 `DailyGitSyncEvening`@20:30 ③提示词是否仍只推企微不落盘 → 重贴本文提示词 C ④立刻 `/run DailyGitSyncEvening` |
| 企微没消息 | key / `delivery.mode` / `NOTIFIER_DRY_RUN` |
| 早盘扫超时 | 正常走 `scanner_with_fallback` → lite；查网络/Zscaler |
| bat Result:1 | `cmd /k` 手动跑 bat；看对应 `output\*.log` |
| 波段赚亏永远 0 | 看 `sim_trades` account_id=3；机会分是否从未成交 |
| 盘中完全没提醒 | 查 `QuantLearn_QuantPulse` 是否启用+重复间隔；日志 `quant_pulse.log`；持续时间是否到 **14:50**（误设 4h 会在 13:35 掐断） |
| 波段池一直是旧蓝筹 | 查 `QuantLearn_SwingPool`；看 `output\swing_pool\latest.json` 日期；周末用 `--mode hist` |
| LLM cron error | 交易改 schtasks；别依赖模型在线 |
| Agent「说做了」但远程没有 | 旧提示词只落盘不验收；**补挂 19:15 守夜 + 20:30 Evening**；重贴提示词 B/C |

---

# 给 OpenClaw 的一键口令（主人复制即用）

主人 **只发下面这一句**（细节全在本文，不要另贴长提示）：

```text
读 docs/DEPLOYMENT.md，git pull 后严格按文档从 ★ 做到步骤 7。
重点：赚钱闸（弱势日禁买/单票15%/日新建1）+ 挂 QuantLearn_FinanceManager@15:35 落盘 finance-report。
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
