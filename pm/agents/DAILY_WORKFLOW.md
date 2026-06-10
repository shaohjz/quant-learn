# 每日自动研发闭环

## 目标
每天读取 QuantLearn 当天产生的盘前、盘中、盘后、复盘、推送、交易和系统日志，自动形成需求/Bug，驱动研发、测试、部署闭环，并由主 PM 向用户汇报。

## 触发频率
默认每个工作日 18:30 执行一次。若当天不是交易日或无新日志，也要产出一条简短 PM 状态说明。

## 读取范围
优先读取今天相关内容：

1. 运行日志
   - `logs/`
   - `output/`
   - `reports/`
   - `data/`
2. 策略/推送产物
   - `daily_advisor.py` 相关输出
   - `portfolio_alert.py` 相关输出
   - `intraday_scanner.py` 相关输出
   - `push_history` 表
3. 交易和账户数据
   - `data/sim_live_mirror.db`
   - `sim_trades`
   - `daily_snapshot`
   - `position_notes`
4. 配置文件
   - `config_real.yaml`
   - `config_watchlist.yaml`
   - `config_selection_logic.yaml`
5. PM 目录
   - `pm/requirements/`
   - `pm/bugs/`
   - `pm/test_reports/`
   - `pm/deploy/`
   - `pm/ops/`
   - `pm/data/`

## 每日执行顺序（强制）
1. **状态扭转优先**：先扫描 `testing` 需求和 `fixed` Bug，根据测试报告或基础验证结果做状态扭转。
   - 需求通过：`testing -> done`
   - 需求失败：保持 `testing`，并新建/关联 Bug
   - Bug 回归通过：`fixed -> verified`
   - Bug 回归失败：`fixed -> reopened`
2. **部署已通过项**：扫描 `done` 的需求和 `verified` 的 Bug，调度部署 Agent 执行部署。
   - 部署成功：`done -> deployed` / `verified -> deployed`
   - 部署失败：保持状态，创建 Bug
3. **再提新需求**：只有完成状态扭转和部署后，才允许基于当天日志/用户反馈新增需求。
4. **需求去重**：新增需求前必须读取所有 `REQ-*.md`，避免重复提出上一轮需求；重复则更新已有需求的补充说明，不创建新编号。
5. **再调度研发**：研发优先处理 open/reopened Bug，然后处理 P0/P1 pending 需求。
6. **检查运维/数据**：读取运维和数据 Agent 的日报，将问题纳入 Bug 或需求。
7. **最后汇报**：汇报只突出"今日新增"和"今日变化"，不要机械复述所有历史需求。

## 角色分工

### 1. 需求 Agent
职责：根据当天日志和用户反馈提出产品需求。

输出：
- 新需求写入 `pm/requirements/REQ-XXX.md`
- 状态必须是 `pending`
- 每次最多新增 3 个需求，避免需求泛滥
- 必须说明数据来源，禁止假数据

重点关注：
- 页面可读性和信息组织
- 实盘持仓风险提示
- 观察列表质量
- 推送内容可追溯性
- 复盘效率
- 策略表现归因
- 数据健康/行情更新时间

### 2. 研发 Agent
职责：扫描并处理任务。

优先级：
1. `pm/bugs/` 中 `open` / `reopened` 的 S0/S1 Bug
2. `pm/requirements/` 中 P0 pending 需求
3. P1 pending 需求
4. P2/P3 pending 需求

输出：
- 修改业务代码
- 需求：`pending/in_progress -> testing`
- Bug：`open/reopened -> fixed`
- 必须自测
- 必须 Git commit + push

### 3. 测试 Agent
职责：验收研发交付。

输入：
- `testing` 需求
- `fixed` Bug

输出：
- 测试报告：`pm/test_reports/TEST-YYYY-MM-DD-XXX.md`
- 需求通过：`done`
- 需求失败：保持 `testing` 并新建 Bug
- Bug 通过：`verified`
- Bug 失败：`reopened`

### 4. 部署 Agent
职责：将测试通过的代码部署到生产环境。

输入：
- `pm/requirements/` 中 `done` 的需求
- `pm/bugs/` 中 `verified` 的 Bug

输出：
- 执行部署脚本
- 需求：`done -> deployed`
- Bug：`verified -> deployed`
- `pm/deploy/YYYY-MM-DD-deploy.md` 发布日志

部署流程：
1. git checkout master && git pull
2. 构建（如有需要）
3. 部署到 staging + 冒烟测试
4. 部署到 production + 验证

### 5. 运维监控 Agent
职责：持续监控系统健康状态。

检查项：
- 行情源在线（最新数据 ≤ 5 分钟）
- 交易 API 正常
- 数据库可读写
- 磁盘 < 80% / 内存 < 85%
- cron 任务按时执行

输出：
- `pm/ops/YYYY-MM-DD-ops.md` 巡检报告
- S0/S1 问题 → 自动恢复或创建 Bug

### 6. 数据 Agent
职责：管理数据管道，保证数据完整准确。

检查项：
- 行情数据完整性
- 入库时效性
- 数据质量（空值、异常值）
- 数据补全

输出：
- `pm/data/YYYY-MM-DD-data.md` 数据日报
- 数据问题 → 自动修复或创建 Bug

### 7. 主 PM Agent
职责：监督闭环并汇报。

每天汇报必须包含：
- 今日读取了哪些日志/数据
- 新增需求列表
- 研发处理了哪些需求/Bug
- 测试通过/失败情况
- 部署情况
- 运维/数据健康状态
- 当前阻塞项
- 下一步计划

## 完整流转链路

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
                                                              │
                                                          (deployed)
                                                              │
                                                  ┌───────────┴───────────┐
                                                  ▼                       ▼
                                              运维 Agent             数据 Agent
                                            (持续监控)              (数据管道)
```

## 状态定义

| 状态 | 说明 | 所属阶段 |
|------|------|----------|
| pending | 待研发实现 | 需求/Bug |
| in_progress | 正在开发 | 需求/Bug |
| testing | 已提测，待验收 | 需求 |
| fixed | 已修复，待回归 | Bug |
| done | 测试通过，待部署 | 需求 |
| verified | 回归通过，待部署 | Bug |
| deployed | 已发布上线 | 需求/Bug |
| reopened | 回归失败，重新打开 | Bug |

## 状态纪律
- 未测试的需求不能标 `done`
- 未回归的 Bug 不能标 `verified`
- 未部署的代码不能标 `deployed`
- 测试发现问题必须写 Bug 文件
- 研发优先修 Bug，再做新需求
- 部署前必须确认测试报告通过
- 运维发现 S0/S1 必须立即告警
- 数据缺失必须标记清楚，不能伪造
- 如果子 agent 失败，主 PM 需要接管或降级为人工检查

## 每日输出建议
- `pm/daily/YYYY-MM-DD.md`：每日闭环摘要
- 新增/更新需求文件
- 新增/更新 Bug 文件
- 测试报告
- 部署日志
- 运维巡检报告
- 数据日报
- Git commit 记录
