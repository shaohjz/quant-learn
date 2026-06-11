# 三 Agent 自治量化研发系统设计

> 设计目标：让量化策略**每天自我迭代**，PM 监督汇报，无需人工每日维护。

## 🏛️ 架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                       PM Agent（监督 + 汇报）                      │
│                         每日 22:00 总结                            │
│                         每日 10:00 检查并向用户汇报                  │
└──────────────────────────────────────────────────────────────────┘
                             ▲       ▲
                             │       │
              ┌──────────────┘       └──────────────┐
              │                                     │
┌──────────────────────────┐         ┌──────────────────────────┐
│     Dev Agent（开发）     │         │     QA Agent（测试）      │
│   每日 19:00              │ ───→   │   每日 21:00             │
│   - 读今日实战 review     │         │   - 拉 dev 分支          │
│   - 分析失败/教训         │         │   - 跑回测套件            │
│   - 修改策略代码（dev分支）│         │   - 对比 master 看变好/变坏 │
│   - 提交 PR               │         │   - 通过 → 合并 master    │
│                          │         │   - 不过 → 报告 + 不合并   │
└──────────────────────────┘         └──────────────────────────┘
```

## 📅 时间线（每个交易日 + 周末）

### 交易日（周一-周五）

| 时间 | 角色 | 任务 |
|---|---|---|
| 09:24 | (现有) | 集合竞价快报 |
| 09:31 | (现有) | 开盘 1 分钟点评 |
| 09:30-15:00 | vqlearn live | 实盘运行 |
| 15:05 | (现有) | 收盘复盘 |
| 15:10 | (现有) | daily_review 报告 |
| **17:00** | **Dev Agent** | **读今日实战 + 改策略 + 提交 dev 分支** |
| **19:00** | **QA Agent** | **拉 dev + 跑回测对比 + 决定合不合并** |
| **22:00** | **PM Agent** | **总结今日 dev/qa 工作，写 daily standup** |
| **次日 10:00** | **PM Agent** | **向用户发 standup 简报**（用户上班看到）|

### 周末

| 时间 | 角色 | 任务 |
|---|---|---|
| 周六 14:00 | Dev Agent | 大版本优化（不只是改阈值，可以重构） |
| 周六 18:00 | QA Agent | 跑全量回测（22 只 × 2 年）+ 综合评估 |
| 周日 10:00 | PM Agent | 周报：本周策略演进、最优参数、下周计划 |

## 🤖 Agent 角色详解

### 👨‍💻 Dev Agent（开发员）

**身份**：策略改进员，懂量化逻辑，目标"提升整体收益 / 减少回撤"。

**输入**：
- `output/reviews/YYYY-MM-DD.md` 今日实战复盘
- `data/sim_live_mirror.db` 今日所有 sim_trades + threshold_state
- `output/vqlearn_backtest_summary.csv` 历史回测基线
- `vqlearn/config/portfolio.yaml` 当前阈值配置
- `vqlearn/strategies/threshold_strategy.py` 当前策略代码

**任务**：
1. 分析今日实战结果（哪些信号准、哪些误触发、哪些没触发该触发）
2. 找出可优化点（阈值调整？规则补充？过滤条件？）
3. 在 `dev` 分支修改代码
4. 写 commit message 解释为什么改

**输出**：
- Git commit 在 `dev` 分支
- `dev/reports/YYYY-MM-DD-dev.md`：今日改动说明 + 预期改进点

**约束**：
- 只能改 `vqlearn/strategies/`、`vqlearn/config/`、`scripts/sim_executor.py`
- 不能改 `master` 分支
- 不能动数据文件 / `data/sim_live_mirror.db`
- 单次改动控制在 200 行以内

### 🧪 QA Agent（测试员）

**身份**：质检员，目标"保护 master 不被坏改动污染"。

**输入**：
- Dev Agent 的 commit on `dev` 分支
- `master` 分支的当前回测基线

**任务**：
1. `git checkout dev`
2. 跑回测套件（22 只 × 2 年 历史）
3. 对比 `master` 基线：总收益变好？回撤变好？胜率变好？
4. **三选一**：
   - **批准**：dev 比 master 好 → `git merge dev` 到 master，next-day live 用新代码
   - **退回**：dev 比 master 差 → 写明哪里差，让 dev 明天改
   - **观察**：差不多（涨跌互现） → 留 dev 分支再观察 1-2 天

**输出**：
- `qa/reports/YYYY-MM-DD-qa.md`：回测对比表 + 决定 + 理由
- 必要时执行 `git merge` 命令

**约束**：
- 不能修改代码
- 通过的合并标准必须**量化**（不能"我觉得好"）：例如年化 +1% 且回撤不变差 → 通过
- 不能跳过测试直接合并

### 📊 PM Agent（项目经理）

**身份**：项目经理，对人（用户）负责，目标"让用户睡好觉，知道系统在干什么"。

**输入**：
- Dev / QA 当日报告
- Live trade 当日数据
- Git log of dev/master

**任务**：
1. 22:00 收集今天 Dev / QA 工作成果
2. 写 daily standup（200 字以内，简洁有力）
3. 第二天 10:00 推送给用户

**输出格式范例**：
```
📊 量化系统 Daily Standup · 2026-05-22

🤖 Dev：今日改了 buy_zone 拒触发逻辑（加大盘过滤），commit: a3f5b2
🧪 QA：跑了 22 股 × 2 年回测，dev vs master：年化 +1.2%、回撤 -2.3% → ✅ 已合并 master
📈 实盘：今日 3 单（圣龙/赣能 BUY，天通 SELL_HALF），浮盈 +¥350
🎯 明日重点：观察大盘过滤是否有效，看新代码会不会减少误触发

详细报告：dev/reports/2026-05-22-dev.md, qa/reports/2026-05-22-qa.md
```

## 🛠️ 实现方式（OpenClaw cron + isolated session）

### 启动一个 Dev Agent 任务

```js
cron.add({
  name: "dev-agent-daily",
  schedule: { kind: "cron", expr: "0 17 * * 1-5", tz: "Asia/Shanghai" },
  sessionTarget: "isolated",
  payload: {
    kind: "agentTurn",
    message: `你是 Dev Agent。任务：分析今日实战 + 改进策略。
    
1. 读 output/reviews/$(today).md
2. 读 data/sim_live_mirror.db 拿今日 sim_trades / threshold_state
3. 找出今日可优化点
4. cd quant-learn && git checkout dev (or create if not exist)
5. 改代码（仅 vqlearn/strategies/ vqlearn/config/ scripts/sim_executor.py）
6. git commit -m "<改动描述>"
7. 写 dev/reports/YYYY-MM-DD-dev.md（含：诊断、改动、预期效果）
8. 不要 push（master 由 QA 决定）

约束：单次改动 ≤ 200 行；不动 master；不动数据文件。

完成后回复"DEV_DONE"。`,
    timeoutSeconds: 1800,
  },
  delivery: { mode: "none" }, // 不直接给用户
});
```

### 启动一个 QA Agent 任务

```js
cron.add({
  name: "qa-agent-daily",
  schedule: { kind: "cron", expr: "0 19 * * 1-5", tz: "Asia/Shanghai" },
  sessionTarget: "isolated",
  payload: {
    kind: "agentTurn",
    message: `你是 QA Agent。任务：测试 dev 分支策略改动。

1. cd quant-learn && git checkout dev
2. 跑：python -m vqlearn.runners.run_backtest_v2 --start 2024-01-01 --end 2026-05-21
3. 对比 master 的 output/baseline_backtest.csv
4. 写 qa/reports/YYYY-MM-DD-qa.md（对比表 + 决定）
5. 三选一：
   - 批准：git merge dev to master + 写报告
   - 退回：写 dev_feedback.md 让 dev 明天看
   - 观察：什么也不做，写报告说"continue observe"
6. 完成后回复"QA_DONE"。

合并标准：年化 +1% 且 回撤不变差 → 通过`,
    timeoutSeconds: 3600,
  },
  delivery: { mode: "none" },
});
```

### 启动一个 PM Agent 任务

```js
cron.add({
  name: "pm-agent-daily",
  schedule: { kind: "cron", expr: "0 22 * * 1-5", tz: "Asia/Shanghai" },
  sessionTarget: "isolated",
  payload: {
    kind: "agentTurn",
    message: `你是 PM Agent。汇总今天 Dev/QA 工作给用户。

1. 读 dev/reports/$(today)-dev.md
2. 读 qa/reports/$(today)-qa.md
3. 读 docs/reviews/$(today).md（实盘）
4. 写 200 字内 standup，发给用户
5. 必须包含：Dev 做了什么 / QA 是否合并 / 实盘表现 / 明日重点

格式见 docs/STRATEGY_AGENTS.md`,
    timeoutSeconds: 600,
  },
  delivery: {
    mode: "announce",
    channel: "wecom",
    to: "T60540021A",
  },
});
```

## ⚠️ 风险点 & 守护机制

### 风险 1：Dev Agent 写出垃圾代码 / 删了关键文件
**守护**：
- Dev 只能在 `dev` 分支
- master 由 QA 决定合并
- 用 `git restore` 可回滚
- 关键文件加 read-only：`data/`, `output/reviews/`

### 风险 2：QA Agent 标准过松 / 过严
**守护**：
- 量化合并标准（年化 +1% 且回撤 ≤ 基线）写死在 PM 监督逻辑里
- 每周 PM 周报里写"本周合并几次、退回几次"，让用户感知

### 风险 3：连续 N 天 dev 都失败 → 卡死
**守护**：
- 第 3 次失败时，PM 主动告警："Dev 连续 3 天没通过 QA，可能策略已遇瓶颈"
- 用户决定是否人工介入

### 风险 4：cron 任务超时 / 失败
**守护**：
- 每个 cron 配 `timeoutSeconds`
- failureAlert 配置（连续 2 次失败发企微通知）

### 风险 5：实盘亏损放大（坏代码上了 master）
**守护**：
- 合并到 master 后**不立即 live**
- 第二天 9:25 PM 再做一次"上线前确认"
- 第一周可以**双跑**（live 跑 master，shadow 跑 dev），对比效果再正式切换

## 🎬 第一阶段实施计划（先做最小可用版）

不一次性铺开，先做最简版：

### Day 1（明天）
- [ ] 把 `quant-learn` 转成 git 仓库（如果还不是）+ 创建 dev 分支
- [ ] 写一个**真正能算 PnL** 的回测引擎（这是基础设施）
- [ ] 跑出 `output/baseline_backtest.csv` 作为 master 基线

### Day 2-3
- [ ] 写 Dev Agent 的 cron 配置 + 测试一次（手动触发，看输出）
- [ ] 写 QA Agent 的 cron 配置 + 测试一次

### Day 4-5
- [ ] 串联三 agent，让他们自动跑 1 个交易日
- [ ] PM 汇报第一份 standup

### 之后
- [ ] 每周复盘机制
- [ ] 周末大版本任务
- [ ] 风控模块

---

## 🎯 关键问题需要用户确认

1. **Git 仓库路径？** 现在 `quant-learn` 是不是 git？要不要 push 到工蜂？
2. **是否允许 QA 自动合并 master？** 还是需要人工 review？
3. **第一周要不要双跑（master live + dev shadow）？** 安全但费资源。
4. **回测周期取多长？** 2 年？5 年？
