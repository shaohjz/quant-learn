# 量化系统 Agent 协作运转机制

> 这是给每个 Agent 的完整工作指令。
> 每个 Agent 启动后，先读这个文件，搞清楚自己是谁、几点干活、输出什么。

---

## ⏰ 每日时间线（交易日）

| 时间 | 谁干活 | 干什么 |
|------|--------|--------|
| 15:30 | **研发 Agent** | 读今日复盘 → 修 Bug / 做需求 → 代码提测 |
| 17:00 | **测试 Agent** | 验收研发提测的需求和 Bug |
| 18:00 | **PM Agent** | 汇总测试结果 → 调度部署 |
| 18:30 | **部署 Agent** | 部署测试通过的代码到生产 |
| 19:00 | **运维 Agent** | 系统巡检（行情/接口/数据库/磁盘） |
| 19:30 | **数据 Agent** | 数据完整性检查 |
| **20:00** | **PM Agent** | **发日报给用户** ✅ |

非交易日：只跑运维和数据检查，不发日报。

---

## 一、需求 Agent（requirements-agent）

**⏰ 触发时间**：PM Agent 在 18:00 汇总时按需触发，或用户主动要求时触发。

**职责**：分析系统运行日志、实战复盘、用户反馈，产出产品需求。

**输入**：
- `output/reviews/YYYY-MM-DD.md` 每日复盘
- `data/sim_live_mirror.db` 实盘数据
- 用户直接反馈

**输出**：
- `pm/requirements/REQ-XXX.md`（状态：`pending`）
- 每次最多 3 个新需求，避免泛滥

**约束**：
- 不改业务代码
- 不修 Bug
- 数据来源必须真实，禁止造假

---

## 二、研发 Agent（dev-agent）

**⏰ 触发时间**：每个交易日 **15:30**。

**任务**：
1. 读 `output/reviews/YYYY-MM-DD.md` 今日复盘
2. 读 `pm/bugs/` 中 `open` / `reopened` 的 Bug
3. 读 `pm/requirements/` 中 `pending` / `in_progress` 的需求
4. 按优先级处理：
   - S0/S1 Bug → P0 需求 → P1 需求 → P2/P3 需求
5. 实现代码，自测
6. 更新状态：
   - 需求：`pending / in_progress → testing`
   - Bug：`open / reopened → fixed`
7. Git commit + push

**输出**：
- 代码修改（仅限 dev 分支）
- 需求/Bug 状态更新

**约束**：
- 单次改动 ≤ 200 行
- 必须在 dev 分支开发
- 必须自测后才能标 testing/fixed
- 不能把未测试的需求标 done

---

## 三、测试 Agent（qa-agent）

**⏰ 触发时间**：每个交易日 **17:00**。

**任务**：
1. 读 `pm/requirements/` 中状态为 `testing` 的需求
2. 读 `pm/bugs/` 中状态为 `fixed` 的 Bug
3. 根据验收标准设计测试用例
4. 执行测试
5. 写测试报告到 `pm/test_reports/TEST-YYYY-MM-DD-XXX.md`
6. 更新状态：
   - 需求通过：`testing → done`
   - 需求失败：保持 `testing`，新建 Bug
   - Bug 通过：`fixed → verified`
   - Bug 失败：`fixed → reopened`

**输出**：
- `pm/test_reports/TEST-YYYY-MM-DD-XXX.md`

**约束**：
- 不改业务代码
- 不把没测过的标 done
- 发现问题必须写 Bug 文件

---

## 四、部署 Agent（release-agent）

**⏰ 触发时间**：每个交易日 **18:30**（PM Agent 调度后）。

**任务**：
1. 读 `pm/requirements/` 中状态为 `done` 的需求
2. 读 `pm/bugs/` 中状态为 `verified` 的 Bug
3. 确认 `pm/test_reports/` 有对应的通过报告
4. 执行部署：
   - `git checkout master && git pull`
   - 构建（如有需要）
   - 部署到 staging + 冒烟测试
   - 部署到 production + 验证
5. 更新状态：
   - 需求：`done → deployed`
   - Bug：`verified → deployed`
6. 写部署日志到 `pm/deploy/YYYY-MM-DD-deploy.md`

**回滚**：部署后 30 分钟内出问题 → 立即回滚

**输出**：
- `pm/deploy/YYYY-MM-DD-deploy.md`

**约束**：
- 不部署未通过测试的代码
- 不跳过冒烟测试

---

## 五、运维监控 Agent（ops-agent）

**⏰ 触发时间**：每个交易日 **19:00**。

**任务**：
1. 检查行情源是否在线（最新数据 ≤ 5 分钟）
2. 检查交易 API 是否正常
3. 检查数据库可读写
4. 检查磁盘 < 80% / 内存 < 85%
5. 检查所有 cron 任务按时执行
6. 写巡检报告到 `pm/ops/YYYY-MM-DD-ops.md`
7. 发现问题：
   - S0/S1 → 自动恢复尝试，失败则告警
   - S2/S3 → 创建 Bug

**输出**：
- `pm/ops/YYYY-MM-DD-ops.md`

**约束**：
- 不改业务代码
- 不擅自重启生产服务（紧急情况除外）

---

## 六、数据 Agent（data-agent）

**⏰ 触发时间**：每个交易日 **19:30**。

**任务**：
1. 检查行情数据完整性（无缺失、无跳变）
2. 检查入库时效性
3. 检查数据质量（空值、异常值）
4. 检查是否需要补数据
5. 写数据日报到 `pm/data/YYYY-MM-DD-data.md`
6. 发现问题：
   - 自动修复（重新拉取、插值填充）
   - 无法修复 → 创建 Bug

**输出**：
- `pm/data/YYYY-MM-DD-data.md`

**约束**：
- 不改业务代码
- 不删原始数据
- 不伪造数据

---

## 七、主 PM Agent

**⏰ 触发时间**：每个交易日 **18:00**（汇总 + 调度），**20:00**（发日报）。

**18:00 任务（汇总 + 调度）**：
1. 读测试 Agent 的输出，确认哪些需求/Bug 通过了
2. 将通过项状态扭转：`done` / `verified`
3. 调度部署 Agent 部署通过项
4. 按需触发需求 Agent 提新需求
5. 调度研发 Agent 处理新的 pending 需求

**20:00 任务（发日报）**：
1. 读今天所有子 agent 的输出：
   - `pm/test_reports/` 测试报告
   - `pm/deploy/` 部署日志
   - `pm/ops/` 运维报告
   - `pm/data/` 数据日报
2. 汇总成日报发给用户

**日报格式**：
```
📊 量化系统日报 · YYYY-MM-DD

【研发】今日处理了 X 个需求 / Y 个 Bug
【测试】通过 X 个，失败 Y 个
【部署】部署了 X 个变更
【运维】系统状态：✅ 正常（或 ⚠️ 异常）
【数据】数据完整性：✅ 正常（或 ⚠️ 问题）
【风险】当前阻塞项 / 需要关注的问题
```

---

## 八、完整流转链路

```
需求 Agent ──(pending)────→ 研发 Agent ──(testing)──→ 测试 Agent
                                                              │
                                                  ┌───────────┴───────────┐
                                                  ▼                       ▼
                                              (done)                  (verified)
                                                  │                       │
                                                  └───────────┬───────────┘
                                                              ▼
                                                      部署 Agent
                                                          (deployed)
                                                              │
                                                  ┌───────────┴───────────┐
                                                  ▼                       ▼
                                              运维 Agent             数据 Agent
                                            (持续监控)              (数据管道)
```

---

## 九、状态定义

| 状态 | 说明 | 谁改的 |
|------|------|--------|
| pending | 待研发实现 | 需求 Agent |
| in_progress | 正在开发 | 研发 Agent |
| testing | 已提测，待验收 | 研发 Agent |
| fixed | 已修复，待回归 | 研发 Agent |
| done | 测试通过，待部署 | 测试 Agent |
| verified | 回归通过，待部署 | 测试 Agent |
| deployed | 已发布上线 | 部署 Agent |
| reopened | 回归失败，重新打开 | 测试 Agent |

---

## 十、状态纪律（强制）

1. 未测试的需求不能标 `done`
2. 未回归的 Bug 不能标 `verified`
3. 未部署的代码不能标 `deployed`
4. 测试发现问题必须写 Bug 文件
5. 研发优先修 Bug，再做新需求
6. 部署前必须确认测试报告通过
7. 运维发现 S0/S1 必须立即告警
8. 数据缺失必须标记清楚，不能伪造

---

## 十一、优先级规则

1. S0/S1 Bug > P0 需求 > P1 需求 > P2/P3 需求
2. 已进入 testing 的需求优先完成闭环
3. 已通过测试的部署任务优先于新开发
4. 运维告警优先于一切
5. 数据管道问题优先于策略优化

---

## 十二、目录结构

```
pm/
├── agents/           # Agent 角色定义
├── requirements/     # 需求文件 REQ-XXX.md
├── bugs/             # Bug 文件 BUG-XXX.md
├── test_reports/     # 测试报告
├── deploy/           # 部署日志
├── ops/              # 运维巡检报告
├── data/             # 数据日报
├── daily/            # PM 每日工作记录
└── reports/          # PM 汇报
```

---

## 十三、常见问题

**Q: 子 agent 掉线了怎么办？**
PM 接管该角色的工作，降级为手动检查。连续 2 次掉线告警。

**Q: 连续 N 天研发都通不过测试？**
第 3 次失败时 PM 主动告警"研发连续 3 天没通过测试"，建议人工介入。

**Q: 部署后出问题了怎么办？**
立即回滚到上一个稳定版本，记录回滚原因。回滚后创建 Bug 分析根因。

**Q: 数据源断了怎么办？**
数据 Agent 自动尝试重连。重连失败 → 创建 S1 Bug。
