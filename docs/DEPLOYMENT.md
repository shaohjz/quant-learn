# 量化项目部署与运行手册（给 OpenClaw）

> **本文权威。** OpenClaw 部署/运维以此为准；`SETUP_GUIDE.md` 作废参考。  
> **项目目的**：模拟验证 → **每天给人（主人）实盘挂单建议**（盘中提醒 + 收盘赚亏）。  
> **默认不代客实盘下单**（除非主人另行要求开 QMT live）。  
>  
> **产机路径（写死）**：`C:\Users\Administrator\.openclaw\workspace\quant-learn`  
> **时区**：`Asia/Shanghai`  
> **配套**：[OPENCLAW_DAILY_RUN.md](./OPENCLAW_DAILY_RUN.md)（**每日运行+推 master，优先读这个**）· [CRON_JOBS.md](./CRON_JOBS.md) · [REALTIME.md](./REALTIME.md) · [REVIEW_LOOP.md](./REVIEW_LOOP.md) · [README.md](../README.md)  
> **更新**：2026-07-19（资金真源统一到 config.yaml accounts.*；learn=10万 / swing=5万；新增 capital_status 自查）

---

## 主人怎么喊你（一句话就够）

主人只需说：

> **读 `docs/OPENCLAW_DAILY_RUN.md` 并按文档部署/检查；需要全量重建再按 `docs/DEPLOYMENT.md` 步骤 0→7。**

或：

> **重新部署：`git pull`，然后严格按 `docs/DEPLOYMENT.md` 文首 ★ 从步骤 0 做到步骤 7。**

你就执行，**不要另编一套定时器**；做完写 `pm/ops/今天-deploy.md` 回复。

### 文档同步（给 Cursor / 提交者）

改了调度、runner bat、波段池、Pulse/日报入口时，**同一次提交必须改** `docs/DEPLOYMENT.md`（及必要时 `CRON_JOBS.md` / `REALTIME.md`）。  
项目已挂 Cursor hook：`git commit` 若漏改部署文档会拦截提醒。

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
.venv\Scripts\python.exe -u scripts\swing_pool_builder.py --top 20 --mode hist --force

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
| A2 | `output\swing_pool\latest.json` 存在且 `stocks` 约 20 只；`data_mode` 为 hist/live |
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

REM ①b 08:40 动态稳定波段池 Top20（优胜劣汰）
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

### 波段池说明（2026-07-17）

| 项 | 内容 |
|----|------|
| 脚本 | `scripts/swing_pool_builder.py` + `swing_pool_builder_runner.bat` |
| 任务 | `QuantLearn_SwingPool` **08:40** 必开 |
| 池大小 | **Top20**（优胜劣汰：每日重排，分低出局） |
| 底池 | 沪深300+中证500（`data/universe_cache.json`） |
| 盘中扫谁 | Pulse → `swing_intraday_watch` 读 `output/swing_pool/latest.json` |
| 周末 | `--mode hist`（日K）；`auto` 周末自动 hist |
| 持仓 | 账户 #3 持仓强制保留在池内 |
| 兜底 | latest 缺失 → 旧 `STOCK_POOL` 种子 |
## 步骤 6 — 整理 OpenClaw Cron（LLM 限量）

```bat
openclaw cron list
```

| 动作 | 对象 |
|------|------|
| **全部删/停** | 任何交易扫描、波段扫描、每 N 分钟盯盘的 **LLM agentTurn** |
| **停用（建议）** | 每日多轮「研发修复」LLM（09/18/21） |
| **最多保留 1～2 条** | 晚间文案：按 [REVIEW_LOOP.md](./REVIEW_LOOP.md) 写 `pm/` + `cursor_queue`（可合并成 **18:15 一条**） |
| **不要** | schtasks 已跑的脚本再在 OpenClaw 挂一份（双推） |

可选：若不用 schtasks，交易脚本可用 OpenClaw **`systemEvent`（非 LLM）** 调 bat/python——仍算「脚本调度」，不占 LLM 名额。优先 schtasks。

## 步骤 7 — 交付报告

写入 `pm/ops/YYYY-MM-DD-deploy.md`，必须包含：

1. `git log -1 --oneline`  
2. 冒烟 A～E 结果  
3. **【Windows schtasks】** `findstr QuantLearn` 原文 + Pulse 是否已在 GUI 设 10 分重复  
4. **【OpenClaw cron】** 最终 list 原文（应几乎无交易 LLM）  
5. 已停用的重复/LLM 任务名  
6. 企微是否真推测过（是/否）  

报告里 **必须分开两节**写 schtasks 与 openclaw cron，禁止混在一堆。

---

# 主人每天会收到什么（你要保证这套在跑）

```
【全是 Windows schtasks，不是 OpenClaw LLM cron】
08:30            MorningScan 宽基扫
08:40            SwingPool 动态稳定池 Top20（优胜劣汰；周末可用 hist）
09:35~14:50 /10m QuantPulse（GUI 设重复）真仓阈值+波段(扫池)+指数
10:00~14:30 /30m IntradayScanner（可选，GUI 设重复）
16:05            SwingDaily 波段赚亏+挂单建议
16:15            TradeJournal 台账
16:20            DailyClose 双账户摘要

【OpenClaw LLM：最多 1～2 条】
18:15 左右        需求入库 + 写 pm/cursor_queue（可合并成一条）

【Windows schtasks 晚间同步】
18:45            DailyGitSync 台账/PM/QA/Ops → push master
```
详情：[REALTIME.md](./REALTIME.md) · [REVIEW_LOOP.md](./REVIEW_LOOP.md)

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

# 日常运维（OpenClaw 心跳时可做）

交易日抽查：

```bat
schtasks /query /tn QuantLearn_QuantPulse /v /fo LIST
schtasks /query /tn QuantLearn_SwingDaily /v /fo LIST
dir output\swing_daily
dir pm\trade_journal
dir output\scan
type output\quant_pulse.log
```

异常时优先查：[REALTIME.md](./REALTIME.md) 误解表 + 下文排障。

---

# 故障排查

| 现象 | 处理 |
|------|------|
| 企微没消息 | key / `delivery.mode` / `NOTIFIER_DRY_RUN` |
| 早盘扫超时 | 正常走 `scanner_with_fallback` → lite；查网络/Zscaler |
| bat Result:1 | `cmd /k` 手动跑 bat；看对应 `output\*.log` |
| 波段赚亏永远 0 | 看 `sim_trades` account_id=3；机会分是否从未成交 |
| 盘中完全没提醒 | 查 `QuantLearn_QuantPulse` 是否启用+重复间隔；日志 `quant_pulse.log` |
| 波段池一直是旧蓝筹 | 查 `QuantLearn_SwingPool`；看 `output\swing_pool\latest.json` 日期；周末用 `--mode hist` |
| LLM cron error | 交易改 schtasks；别依赖模型在线 |

---

# 给 OpenClaw 的一键口令（主人复制即用）

主人只需发下面这一段（细节全在本文 ★，不要另写长提示）：

```text
重新部署 quant-learn：
cd C:\Users\Administrator\.openclaw\workspace\quant-learn
git pull
然后严格按 docs/DEPLOYMENT.md 文首「★ OpenClaw：如何跑这个项目」从步骤 0 做到步骤 7。
重点确认：QuantLearn_SwingPool（08:40）已创建且 Ready；冒烟含 swing_pool_builder --mode hist。
定时器用 Windows schtasks（见文内「两套定时器」）；OpenClaw LLM cron ≤1～2 条。
做完写 pm/ops/今天-deploy.md 回复我。
```

---

# 相关文档

| 文档 | 用途 |
|------|------|
| [REVIEW_LOOP.md](./REVIEW_LOOP.md) | **每日复盘 / 多角色 / Cursor 队列（治理轨道）** |
| [REALTIME.md](./REALTIME.md) | 实时监控全景 / 大盘扫不扫 |
| [CRON_JOBS.md](./CRON_JOBS.md) | 全量任务表与历史 ID |
| [ROADMAP.md](./ROADMAP.md) | 需求与缺陷 |
| [qmt_integration.md](./qmt_integration.md) | QMT（可选） |
| [wecom_webhook_setup.md](./wecom_webhook_setup.md) | 企微 |
