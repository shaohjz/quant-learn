# 产品需求管理

## 角色分工
- **产品/PM（主 agent）**：提出需求、拆优先级、验收标准、维护需求/Bug 看板、每30分钟汇报。
- **需求 agent**：只负责往 `pm/requirements/` 产出新的 `pending` 需求，不改代码。
- **研发 agent**：读取 `pending` 需求和 `open/reopened` Bug，实现需求、修复 Bug，完成后状态改为 `testing` / `fixed`。
- **测试 agent**：按验收标准测试需求，发现问题提 Bug，回归 fixed Bug，测试通过后改 `done` / `verified`。

## 强制流程
1. PM 先做状态扭转：`testing -> done`，`fixed -> verified`。
2. PM 再根据当天日志/反馈提出新需求，避免只重复上一轮需求。
3. 研发优先修 Bug，再做需求。
4. 测试必须写报告，未测试不得标 done/verified。

## 需求状态定义
- `pending` - 待开发
- `in_progress` - 开发中
- `testing` - 研发完成，待测试
- `done` - 测试通过
- `blocked` - 被 Bug 或外部因素阻塞
- `rejected` - 已拒绝

## 当前需求列表

| ID | 标题 | 优先级 | 状态 | 创建时间 | 负责人 |
|---|---|---|---|---|---|
| REQ-001 | UI浅色主题优化 | P1 | done | 2026-05-25 | 主agent |
| REQ-002 | 收益率曲线图 | P0 | done | 2026-05-25 | dev-agent-req002 |
| REQ-003 | 持仓饼图+统计页增强 | P1 | done | 2026-05-25 | 主agent接手 |
| REQ-004 | 实时刷新动画+更新提示 | P1 | done | 2026-05-25 | dev-agent-req004 |
| REQ-005 | 观察列表K线缩略图 | P2 | pending | 2026-05-25 | - |
| REQ-006 | 快捷操作面板 | P2 | pending | 2026-05-25 | - |
| REQ-007 | 暗色/浅色主题切换 | P3 | pending | 2026-05-25 | - |
| REQ-008 | 每日PM自动状态扭转与新需求生成 | P0 | pending | 2026-05-25 | PM |
| REQ-009 | PM需求去重与需求池分层看板 | P1 | pending | 2026-05-25 | PM |
| REQ-010 | 研发/测试 Agent 失败自动降级接管机制 | P1 | pending | 2026-05-25 | PM |

## 当前 Bug 列表

| ID | 标题 | 严重级别 | 状态 | 关联需求 |
|---|---|---|---|---|
| BUG-001 | REQ-003统计API返回JSON不完整/异常 | S1 | verified | REQ-003 |
| BUG-002 | scanner fallback 在 Windows GBK 输出下因 Emoji 打印崩溃 | S1 | verified | 无 |

## 优先级说明
- **P0**: 核心体验缺失或流程阻塞，必须优先做
- **P1**: 本周内完成，显著提升体验
- **P2**: 有空就做，锦上添花
- **P3**: 低优先级

## 标准协作流程
1. PM/需求 agent 写需求 → `pm/requirements/REQ-XXX.md`，状态 `pending`
2. 研发领取需求 → 状态 `in_progress`
3. 研发实现 → 自测通过 → 状态 `testing`
4. 测试验收 → 通过：状态 `done`；失败：提 `pm/bugs/BUG-XXX.md`
5. 研发修 Bug → Bug 状态 `fixed`
6. 测试回归 → 通过：Bug `verified`；失败：Bug `reopened`
7. PM 每30分钟汇报：需求进度 + Bug 进度 + 风险

## 需求文件规范
每个需求一个文件：`pm/requirements/REQ-XXX.md`

## Bug 文件规范
每个 Bug 一个文件：`pm/bugs/BUG-XXX.md`
