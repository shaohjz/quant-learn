# 每日复盘与多角色迭代规划（OpenClaw 轻量 + Cursor 重活）

> **问题**：角色很多（理财经理 / 开发经理 / 测试 / PM / 需求），以前设计成 OpenClaw 自动改代码；  
> 但 OpenClaw 模型弱 → 容易乱改、消化不了大仓库。  
> **解法**：**OpenClaw 只做观察、写需求/Bug、改状态、排队**；**真改代码由你在 Cursor 手动触发（或 Cursor Cloud Agent）**。  
> 更新：2026-07-14

配套：已有机制见 `docs/FULL_AGENT_PROMPT.md`、`pm/agents/*`、`scripts/pm_cli.py`。  
本文是 **新主契约**，与旧「Dev Agent 15:30 自动改代码」冲突处以本文为准。

---

## 1. 目标一句话

```
交易日运行 → 各角色复盘提问 → 写入 git(pm/) + pm.db
     → 每晚生成「给 Cursor 的修复队列」
     → 你有空时在 Cursor 说「按队列修 P0」→ 合入 → 改状态
```

自动优化 ≠ OpenClaw 半夜改策略；  
自动优化 = **自动发现问题 + 自动排队 + 你触发强模型落地**。

---

## 2. 角色分工（谁干什么、什么不做）

| 角色 | OpenClaw 能否做 | 做什么 | **禁止** |
|------|----------------|--------|----------|
| **理财经理** Finance | ✅ 轻量 | 读模拟盘/波段结论，写「行情+账户」复盘；可提 P1/P2 产品建议 | 改 `scripts/` / 策略代码 |
| **需求** Requirements | ✅ 轻量 | 从复盘/日志提炼 `REQ-xxx.md`，写入 `pm.db`，优先级 | 写实现代码 |
| **PM** | ✅ 轻量 | 排期、去重、日报、维护 backlog、指定「今日 Cursor 队列」 | 大改代码 |
| **开发经理** Dev-Mgr | ⚠️ 只分析 | 读失败测试/日志，写「修复方案草稿」进 `pm/dev/` | 擅自大范围 commit |
| **测试** QA | ✅ 轻量 | 跑 pytest（或读报告）、写 `TEST-*.md`、改 testing→done / reopen | 改业务逻辑「凑绿」 |
| **运维** Ops | ✅ 轻量 | 查 schtasks/日志/数据源，写 ops 报告、开 Bug | 乱删任务 |
| **Cursor（你触发）** | — | **唯一默认允许改业务代码的执行器** | — |

OpenClaw 模型弱时：**Dev 角色降级为「写方案 + 贴文件路径」**，不直接改仓控/止损核心。

---

## 3. 状态机（统一，写入 git + pm.db）

### 需求 REQ

```
pending → ready（PM 确认可做）→ in_progress（Cursor 认领）
       → testing（代码已交测）→ done → deployed
失败：testing → pending（并开 BUG）
```

### Bug

```
open → in_progress → fixed → verified → deployed
失败：fixed → reopened
```

命令（已有）：

```bat
.venv\Scripts\python.exe scripts\pm_cli.py create --type story --title "..." --priority P0
.venv\Scripts\python.exe scripts\pm_cli.py update REQ-048 --status testing
.venv\Scripts\python.exe scripts\pm_cli.py list --status pending
```

文件落盘（给人/Cursor 看）：

| 类型 | 路径 |
|------|------|
| 需求 | `pm/requirements/REQ-xxx.md` |
| Bug | `pm/bugs/BUG-xxx.md` |
| 测试报告 | `pm/test_reports/TEST-YYYY-MM-DD-xxx.md` |
| 理财复盘 | `output/reviews/` 或 `pm/daily/` |
| **Cursor 队列** | `pm/cursor_queue/YYYY-MM-DD.md` ← **新增核心** |
| 开发方案草稿 | `pm/dev/PLAN-REQ-xxx.md` |

---

## 4. 每日时间线（交易日，推荐）

与交易调度错开，避免抢盘中。

| 时间 | 谁 | 动作 | 模型强度 |
|:----:|----|------|----------|
| 15:10 | 系统 bat | `daily_review` / 持仓摘要（已有） | 脚本 |
| 16:05 | 系统 bat | 波段日报赚亏（已有） | 脚本 |
| **16:30** | **理财经理** | 读波段结论+账户 → 写短复盘；可选提 0–2 条 REQ | OpenClaw 短会话 |
| **17:00** | **需求 + PM** | 消化复盘/ops/日志 → 开/更新 REQ·BUG；**去重**；标 priority | OpenClaw |
| **17:30** | **QA** | `pytest -q`（或读昨日失败）→ 更新 testing 项；失败开 BUG | OpenClaw 或 bat |
| **18:00** | **开发经理** | **只写方案**：对每个 P0 写 `PLAN-*.md`（改哪些文件、验收标准） | OpenClaw |
| **18:15** | **PM** | 生成 **`pm/cursor_queue/今天.md`**（给 Cursor 的修复菜单） | OpenClaw |
| **18:30** | **PM → 你** | 企微一条：「今日队列 N 条 P0，在 Cursor 执行：…」 | OpenClaw 投递 |
| （你空时） | **你 + Cursor** | 打开队列，按条修、自测、commit | **Cursor 强模型** |
| 次日盘前 | PM/QA | 看你昨晚 commit → 把对应 REQ 标 testing/done | OpenClaw |

非交易日：只跑 QA 摘要 + PM 整理 backlog，不刷行情复盘。

---

## 5. Cursor 队列格式（强制，方便你一键开干）

每天 PM（或脚本）写出：

`pm/cursor_queue/YYYY-MM-DD.md`

```markdown
# Cursor 修复队列 2026-07-14

> 在 Cursor 对话里说：按 pm/cursor_queue/今天.md 从 P0 往下做，每项单独 commit。

## P0（今晚必做，≤3 条）
### 1. REQ-048 止损状态已 executed 仓还在
- 状态: testing
- 方案: pm/dev/PLAN-REQ-048.md
- 关键文件: vqlearn/services/threshold_state.py, scripts/sim_executor.py
- 验收: pytest tests/test_req057_req048_fix.py 全绿
- 做完: pm_cli update REQ-048 --status done

### 2. ...

## P1（有空再做）
- ...

## 不要动
- REQ-011 vnpy OmsEngine（大需求，另开专轮）
- 不要改 config.local.yaml / webhook
```

你在 Cursor 触发话术（复制）：

```text
读 pm/cursor_queue/今天的日期.md，只做 P0。
每项：按 PLAN 改代码 → 跑写明的 pytest → 通过则 pm_cli 改状态 → 单独 commit。
不碰「不要动」列表。做完更新队列文件打勾。
```

---

## 6. OpenClaw 各角色提示词要点（瘦身版）

### 理财经理（16:30）

```text
只读：output/swing_daily/今天.md、sim 账户摘要、当日告警。
输出：pm/daily/YYYY-MM-DD-finance.md（短：赚亏、持仓风险、1～2 句建议）。
若发现系统问题：用 pm_cli 开 BUG/REQ，不要改代码。
```

### 需求（17:00）

```text
输入：finance 复盘、ops 日志、失败测试。
规则：每日新建 REQ ≤ 3；先 list 去重；写 pm/requirements/REQ-xxx.md + pm_cli create。
禁止改业务代码。
```

### PM（18:15）

```text
输入：pending/open 的 REQ/BUG、今日 finance、QA 报告。
输出：1) 更新优先级 2) 写 pm/cursor_queue/今天.md（P0≤3）
3) 企微通知主人队列摘要。
禁止自己大改代码。
```

### 开发经理（18:00）

```text
对每个 P0：写 pm/dev/PLAN-REQ-xxx.md
必须含：根因假设、改哪些路径、测试命令、风险。
禁止直接改 strategies/止损核心超过「贴补丁级」；默认留给 Cursor。
```

### QA（17:30）

```text
跑或汇总 pytest；更新 TEST 报告；testing 项不通过 → Bug + reopen。
禁止为了绿而改断言或业务。
```

---

## 7. 和交易调度的关系（别搅在一起）

| 轨道 | 内容 | 调度 |
|------|------|------|
| **交易轨道** | pulse / 大盘扫 / 波段日报 | schtasks（见 DEPLOYMENT） |
| **治理轨道** | 理财/需求/PM/QA/队列 | OpenClaw cron **agentTurn 短任务** 或你手动 |

治理轨道 **晚于 16:05**，用复盘产物当输入。  
OpenClaw 挂治理任务时：`timeout` 短、只写 `pm/`，输出目录白名单。

---

## 8. 分阶段落地（务实）

### 阶段 A（本周就能用）— 推荐先做

1. 固定产出目录：`pm/cursor_queue/`、`pm/dev/`  
2. 每天 18:15 **一个** OpenClaw「PM 排队」任务：读 pm.db + 写队列 md + 推企微  
3. 理财复盘：复用/缩短现有理财师 cron，**只写 md，不改代码**  
4. 你用 Cursor 消化 P0  

### 阶段 B

1. QA 用 bat：`pytest -q > output/pytest_daily.txt`，OpenClaw 只读结果改状态  
2. 需求 Agent 每日最多 3 条，带去重  
3. 开发经理只出 PLAN  

### 阶段 C（可选）

1. Cursor Cloud / API：对队列 P0 自动开 PR（仍要你点 merge）  
2. 合并后 webhook → 自动 `pm_cli update --status done`  

**不建议**：让弱模型 Dev Agent 每日自动 push 策略代码到 master。

---

## 9. 成功标准

| 指标 | 健康 |
|------|------|
| 每日有无 `cursor_queue/今天.md` | 有 |
| P0 条数 | ≤ 3（多了说明在堆债，先砍范围） |
| OpenClaw 改业务代码 commit | ≈ 0（除非你特批小补丁） |
| Cursor 修完 → 状态更新 | 同一天内能对上 |
| 主人企微 | 1 条队列摘要 + 交易提醒（不刷研发长文） |

---

## 10. 你怎么用（日常三句话）

1. **白天**：看交易提醒（DEPLOYMENT 四件套）。  
2. **晚上**：企微看「Cursor 队列」；有空就打开 Cursor 丢上面的话术。  
3. **周末**：PM 出周报；大需求（vnpy/架构）只进 ROADMAP，不进每日 P0。

---

## 11. 给 OpenClaw 的治理口令（晚间）

```text
你是 PM+需求助理（不要改 strategies/scripts 业务代码）。
1. 读今天 output/swing_daily/*.md、pm/bugs、pm/requirements、pytest 日志（若有）
2. 去重后：必要则 pm_cli create REQ/BUG（今天新建 ≤3）
3. 写出 pm/cursor_queue/今天.md：P0≤3，每项含文件路径+验收 pytest+做完改哪个状态
4. 企微发短摘要给主人：今日队列标题列表
5. 写 pm/daily/今天-pm.md 留档
红线：禁止重构交易核心；禁止 force push；禁止动 webhook 密钥。
```

---

## 12. 相关文件

| 路径 | 说明 |
|------|------|
| `docs/DEPLOYMENT.md` | 交易系统怎么跑 |
| `docs/REALTIME.md` | 盘中监控 |
| `docs/FULL_AGENT_PROMPT.md` | 旧全自动设计（Dev 自动改码部分 **作废**，以本文为准） |
| `pm/agents/*.md` | 角色细则可继续沿用「只读/只写 pm」约束 |
| `scripts/pm_cli.py` | 状态工具 |
