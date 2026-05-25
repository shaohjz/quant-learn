# 产品需求管理

## 需求状态定义
- `pending` - 待开发
- `in_progress` - 开发中
- `testing` - 测试中
- `done` - 已完成
- `rejected` - 已拒绝

## 当前需求列表

| ID | 标题 | 优先级 | 状态 | 创建时间 | 负责人 |
|---|---|---|---|---|---|
| REQ-001 | UI浅色主题优化 | P1 | done | 2026-05-25 | 研发agent |

## 待分配需求

（产品经理 agent 会在这里追加新需求）

## 需求文件规范

每个需求一个文件：`pm/requirements/REQ-XXX.md`

格式：
```markdown
# REQ-XXX: 标题

## 背景
为什么要做这个

## 需求描述
具体要做什么

## 验收标准
1. xxx
2. xxx

## 优先级
P0/P1/P2/P3

## 状态
pending/in_progress/testing/done
```
