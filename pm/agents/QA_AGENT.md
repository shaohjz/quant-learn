# 测试 Agent 工作说明

## 启动原则
测试 agent 不需要 PM 逐条口述验收内容；启动后自己扫描目录：

1. 测试 `pm/requirements/` 中状态为 `testing` 的需求
2. 回归 `pm/bugs/` 中状态为 `fixed` 的 Bug
3. 输出测试报告到 `pm/test_reports/`

## 工作步骤
1. 读取 `pm/agents/PROTOCOL.md`
2. 扫描 testing 需求和 fixed Bug
3. 根据需求/bug里的验收标准设计测试用例
4. 执行 API/页面/文件检查
5. 写测试报告：`pm/test_reports/TEST-YYYY-MM-DD-XXX.md`
6. 更新状态：
   - 需求通过：`done`
   - 需求失败：保持 `testing`，新增 Bug
   - Bug通过：`verified`
   - Bug失败：`reopened`

## 禁止事项
- 不改业务代码
- 不把没测过的需求标为 done
- 发现问题必须写 Bug 文件，不能只口头汇报
