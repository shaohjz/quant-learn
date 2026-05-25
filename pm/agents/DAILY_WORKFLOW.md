# 每日自动研发闭环

## 目标
每天读取 QuantLearn 当天产生的盘前、盘中、盘后、复盘、推送、交易和系统日志，自动形成需求/Bug，驱动研发和测试闭环，并由主 PM 向用户汇报。

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
   - `pm/README.md`

## 每日执行顺序（强制）
1. **状态扭转优先**：先扫描 `testing` 需求和 `fixed` Bug，根据测试报告或基础验证结果做状态扭转。
   - 需求通过：`testing -> done`
   - 需求失败：保持 `testing`，并新建/关联 Bug
   - Bug 回归通过：`fixed -> verified`
   - Bug 回归失败：`fixed -> reopened`
2. **再提新需求**：只有完成状态扭转后，才允许基于当天日志/用户反馈新增需求。
3. **需求去重**：新增需求前必须读取所有 `REQ-*.md`，避免重复提出上一轮需求；重复则更新已有需求的补充说明，不创建新编号。
4. **再调度研发**：研发优先处理 open/reopened Bug，然后处理 P0/P1 pending 需求。
5. **最后汇报**：汇报只突出“今日新增”和“今日变化”，不要机械复述所有历史需求。

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

### 4. 主 PM Agent
职责：监督闭环并汇报。

每天汇报必须包含：
- 今日读取了哪些日志/数据
- 新增需求列表
- 研发处理了哪些需求/Bug
- 测试通过/失败情况
- 当前阻塞项
- 下一步计划

## 状态纪律
- 未测试的需求不能标 `done`
- 未回归的 Bug 不能标 `verified`
- 测试发现问题必须写 Bug 文件
- 研发优先修 Bug，再做新需求
- 如果子 agent 失败，主 PM 需要接管或降级为人工检查

## 每日输出建议
- `pm/daily/YYYY-MM-DD.md`：每日闭环摘要
- 新增/更新需求文件
- 新增/更新 Bug 文件
- 测试报告
- Git commit 记录
