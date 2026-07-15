# 量化项目部署与运行手册（给 OpenClaw）

> **本文权威。** OpenClaw 部署/运维以此为准；`SETUP_GUIDE.md` 作废参考。  
> **项目目的**：模拟验证 → **每天给人（主人）实盘挂单建议**（盘中提醒 + 收盘赚亏）。  
> **默认不代客实盘下单**（除非主人另行要求开 QMT live）。  
>  
> **产机路径（写死）**：`C:\Users\Administrator\.openclaw\workspace\quant-learn`  
> **时区**：`Asia/Shanghai`  
> **配套**：[CRON_JOBS.md](./CRON_JOBS.md) · [REALTIME.md](./REALTIME.md) · [ROADMAP.md](./ROADMAP.md) · [README.md](../README.md)  
> **更新**：2026-07-15

---

# ★ OpenClaw：如何跑这个项目（必读，按顺序做）

你是 OpenClaw Agent。主人要的是：**盘中有提醒、收盘知道波段赚亏、能扫大盘找票、每天有交易台账可复盘**。  
按下面步骤执行。每步写清成功/失败。完成后写 `pm/ops/YYYY-MM-DD-deploy.md`。

## 约束（红线）

1. **禁止**用 LLM `agentTurn` 去扫盘、模拟下单、改生产交易代码并自动 merge。  
2. **禁止**把 webhook key 写进 git；放 `config.local.yaml`。  
3. **禁止**开启实盘自动下单（QMT live），除非主人明文说「开 live」。  
4. 交易/扫描类任务用 **schtasks bat** 或 OpenClaw **`systemEvent`**。  
5. 同一功能只留一个入口：有 `QuantLearn_SwingDaily` 就停掉 LLM「短线波段扫描」。

## 步骤 0 — 进入目录

```bat
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
git status
git pull
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

账户约定：

| id | 名字 | 用途 |
|----|------|------|
| **1** | learn | **模拟学习仓**（日常看这个） |
| 2 | real_portfolio | 真仓镜像（可选，默认可关推送） |
| **3** | swing_trade | **波段模拟**（挂单建议 / 波段赚亏） |

## 步骤 4 — 冒烟（必须全绿再挂任务）

```bat
cd /d C:\Users\Administrator\.openclaw\workspace\quant-learn
set NOTIFIER_DRY_RUN=1

REM A 盘中脉搏（真仓阈值 + 波段盯盘 + 指数）
.venv\Scripts\python.exe -u scripts\quant_pulse.py --force --no-push

REM B 波段收盘链路（模拟成交 + 赚亏结论）
.venv\Scripts\python.exe -u scripts\swing_daily_report.py --no-push

REM C 交易台账（全账户成交+持仓 → pm/trade_journal）
.venv\Scripts\python.exe -u scripts\trade_journal.py --no-push

REM D 盘前大盘扫（≈800，失败会 fallback lite）
.venv\Scripts\python.exe -u scripts\scanner_with_fallback.py
```

**成功标准：**

| 检查 | 期望 |
|------|------|
| A | 退出码 0；日志无未捕获 traceback |
| B | 生成 `output\swing_daily\今天日期.md`，含「波段结论」「挂单建议」 |
| C | 生成 `pm\trade_journal\今天日期.md`，含「交易台账」「复盘备注」 |
| D | 有 Top 输出或 fallback 成功；日志写入 `output\morning_scanner.log` 或 runner log |
| DB | 存在账户或 B 后出现 account_id=3 |

任一步失败 → **先修再挂 schtasks**，把错误写进 deploy 报告。

## 步骤 5 — 挂 Windows 计划任务（主调度，这些必须存在）

管理员 CMD：

```bat
set ROOT=C:\Users\Administrator\.openclaw\workspace\quant-learn

REM ① 08:30 宽基大盘扫（≈800）
schtasks /create /f /tn "QuantLearn_MorningScan" /tr "%ROOT%\scripts\morning_scanner_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 08:30

REM ② QuantPulse：先 schtasks 建「每天 09:35 触发一次」，再打开 Windows「任务计划程序」GUI
REM    → 找到 QuantLearn_QuantPulse → 触发器 → 勾选「重复任务间隔」= 10 分钟，持续时间到 14:50
REM    （这是 Windows 计划任务，不是 openclaw cron / 不是 LLM）
schtasks /create /f /tn "QuantLearn_QuantPulse" /tr "%ROOT%\scripts\quant_pulse_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 09:35

REM ③ IntradayScanner：同样用 Windows GUI 设重复 30 分钟到 14:30（可选；消息多就别建）
REM    （也是 Windows 计划任务，禁止做成 OpenClaw LLM 每 30 分一条）
schtasks /create /f /tn "QuantLearn_IntradayScanner" /tr "%ROOT%\scripts\intraday_scanner_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 10:00

REM ④ 16:05 波段日报（赚亏结论）
schtasks /create /f /tn "QuantLearn_SwingDaily" /tr "%ROOT%\scripts\swing_daily_report_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 16:05

REM ⑤ 16:15 交易台账（全账户成交+持仓 → pm/trade_journal，供复盘）
schtasks /create /f /tn "QuantLearn_TradeJournal" /tr "%ROOT%\scripts\trade_journal_runner.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 16:15

schtasks /query /fo LIST | findstr QuantLearn
```

**必开（交易四件套 + 台账）：**

1. `QuantLearn_MorningScan` — 盘前扫大盘  
2. `QuantLearn_QuantPulse` — 盘中真仓+波段+指数  
3. `QuantLearn_IntradayScanner` — 盘中异动发现  
4. `QuantLearn_SwingDaily` — 收盘波段赚亏  
5. `QuantLearn_TradeJournal` — 每日交易记录落盘（复盘用）  

若已单独挂 `PortfolioAlert` / `SwingIntraday`：可保留，或删掉改由 `QuantPulse` 统一调用（避免重复推送）。

试跑：

```bat
schtasks /run /tn QuantLearn_QuantPulse
schtasks /run /tn QuantLearn_SwingDaily
schtasks /run /tn QuantLearn_TradeJournal
type %ROOT%\output\quant_pulse.log
type %ROOT%\output\swing_daily_report.log
type %ROOT%\output\trade_journal.log
dir %ROOT%\pm\trade_journal
```

## 步骤 6 — 整理 OpenClaw Cron

```bat
openclaw cron list
```

| 动作 | 对象 |
|------|------|
| **停用/删除** | 名称含「短线波段扫描」且与 16:05 日报重复的 LLM 任务 |
| **停用（建议）** | 每日多轮「研发修复」LLM（09/18/21），避免半夜改仓控代码 |
| **可保留** | 纯文案日报（PM/理财师），`delivery.mode=announce` |
| **交易类新建** | 只用 `systemEvent` 调 `.venv\Scripts\python.exe -u scripts\...`，或完全交给 schtasks |

波段日报若也用 OpenClaw（可选，schtasks 已够）：

```json
{
  "name": "波段交易日报-systemEvent",
  "schedule": { "kind": "cron", "expr": "5 16 * * 1-5", "tz": "Asia/Shanghai" },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "systemEvent",
    "command": ".venv\\Scripts\\python.exe -u scripts\\swing_daily_report.py"
  },
  "delivery": { "mode": "announce", "channel": "wecom", "to": "jizhouhu" }
}
```

**不要** schtasks + OpenClaw 同时跑同一脚本（双份消息）。

## 步骤 7 — 交付报告

写入 `pm/ops/YYYY-MM-DD-deploy.md`，必须包含：

1. `git log -1 --oneline`  
2. 冒烟 A/B/C 结果  
3. `schtasks` 最终清单（findstr QuantLearn 原文）  
4. `openclaw cron list` 最终清单  
5. 已停用的重复任务名  
6. 企微是否真推测过（是/否）  

---

# 主人每天会收到什么（你要保证这套在跑）

```
08:30  宽基≈800 扫描 → Top 候选（早盘看票）
09:35~14:50  每10分 quant_pulse：
             · 真仓/观察股阈值到价
             · 波段蓝筹好价 / 波段仓止盈止损
             · 指数大跌一句提醒
10:00~14:30  每30分 全市场异动扫描（可进观察池）
16:05  波段模拟成交 +「今天赚/亏」+ 挂单复盘
```

详情：[REALTIME.md](./REALTIME.md)

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
| LLM cron error | 交易改 schtasks；别依赖模型在线 |

---

# 给 OpenClaw 的一键口令（复制即用）

```text
【任务】按 docs/DEPLOYMENT.md「★ OpenClaw：如何跑这个项目」把 quant-learn 跑起来。

目标态（主人要收到）：
- 08:30 宽基大盘扫 Top
- 盘中每10分 quant_pulse（真仓阈值+波段机会+指数）
- 盘中每30分 intraday_scanner（全市场异动）
- 16:05 swing_daily_report（波段赚亏+挂单建议）
- 16:15 trade_journal（全账户成交+持仓 → pm/trade_journal）

必做：
1. cd C:\Users\Administrator\.openclaw\workspace\quant-learn && git pull
2. 确认 .venv；配置 config.local.yaml webhook（勿提交）
3. 冒烟 A quant_pulse --force --no-push；B swing_daily_report --no-push；C trade_journal --no-push；D scanner_with_fallback
4. schtasks 确保：MorningScan / QuantPulse / IntradayScanner / SwingDaily / TradeJournal（Pulse 设10分钟重复到14:50）
5. openclaw cron list：停掉与 SwingDaily 重复的 LLM 波段扫描；交易勿用 agentTurn 下单
6. 写 pm/ops/今天-deploy.md（含 schtasks+cron 原文与试跑结果）

红线：不开启实盘自动下单；密钥不入库；不双开同一扫描；台账数字由脚本写，禁止 LLM 瞎改表格。
参考：docs/REALTIME.md 、docs/CRON_JOBS.md 、docs/REVIEW_LOOP.md
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
