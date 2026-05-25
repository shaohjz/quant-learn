# 研发 Agent 工作说明

## 启动原则
研发 agent 不需要 PM 逐条口述需求；启动后自己扫描目录：

1. 先处理 `pm/bugs/` 中状态为 `open` 或 `reopened` 的 Bug
2. 再处理 `pm/requirements/` 中状态为 `pending` 的需求
3. 优先级顺序：S0/S1 Bug > P0需求 > P1需求 > P2需求 > P3需求

## 工作步骤
1. 读取 `pm/agents/PROTOCOL.md`
2. 扫描 `pm/bugs/*.md` 和 `pm/requirements/*.md`
3. 选择最高优先级的一个任务
4. 将状态改为：
   - 需求：`in_progress`
   - Bug：`in_progress`
5. 实现/修复
6. 自测
7. 状态改为：
   - 需求：`testing`
   - Bug：`fixed`
8. Git commit + push

## 禁止事项
- 不要一次做太多需求，除非高度相关
- 不要跳过 Bug 直接做新需求
- 不要把未经测试的需求改成 `done`
- 不要伪造数据，所有 UI 展示必须来自真实 API/DB/配置
