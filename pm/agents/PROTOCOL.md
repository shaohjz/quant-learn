# Agent 协作协议

## 固定目录
- 需求目录：`pm/requirements/`
- Bug 目录：`pm/bugs/`
- 测试报告目录：`pm/test_reports/`
- Agent 协议目录：`pm/agents/`

## 角色与输入输出

### 1. 需求 Agent（requirements-agent）
**职责**：持续分析系统和用户反馈，产出新需求。

**只写这些文件**：
- `pm/requirements/REQ-XXX.md`
- 可更新 `pm/README.md` 的需求表

**不能做**：
- 不改业务代码
- 不修 Bug
- 不改测试报告

**输出要求**：
每个需求一个 Markdown 文件，状态必须是 `pending`，格式见下方。

### 2. 研发 Agent（dev-agent）
**职责**：扫描 `pm/requirements/` 中 `pending` / `in_progress` 的需求，以及 `pm/bugs/` 中 `open` / `reopened` 的 Bug，按优先级实现。

**输入**：
- `pm/requirements/*.md`
- `pm/bugs/*.md`

**输出**：
- 业务代码修改
- 需求状态：`pending -> in_progress -> testing`
- Bug 状态：`open/reopened -> in_progress -> fixed`
- Git commit + push

### 3. 测试 Agent（qa-agent）
**职责**：扫描 `testing` 的需求和 `fixed` 的 Bug，验收并写报告。

**输出**：
- `pm/test_reports/TEST-YYYY-MM-DD-XXX.md`
- 需求状态：通过 `done`，失败则保留 `testing` 并提 Bug
- Bug 状态：通过 `verified`，失败 `reopened`

### 4. 主 Agent / PM
**职责**：
- 维护流程
- 解决子 agent 掉线时的接管
- 每30分钟汇报：需求、研发、测试、Bug、风险

## 需求文件模板

```md
# REQ-XXX: 标题

## 背景
为什么做。

## 目标用户/场景
谁在什么场景使用。

## 需求描述
具体要做什么。

## 数据来源
展示或计算的数据来自哪里，不能造假。

## 验收标准
1. 可验证标准1
2. 可验证标准2

## 优先级
P0/P1/P2/P3

## 状态
pending
```

## Bug 文件模板

```md
# BUG-XXX: 标题

## 严重级别
S0/S1/S2/S3

## 状态
open

## 关联需求
REQ-XXX

## 现象

## 复现步骤

## 期望结果

## 回归标准
```

## 优先级规则
1. S0/S1 Bug 优先于新需求
2. P0 需求优先于 P1/P2/P3
3. 已经进入 testing 的需求优先完成闭环
4. 不允许同时开太多研发 agent；默认一次最多 1-2 个
