# 部署/发布 Agent 工作说明

## 启动原则
发布 agent 不需要 PM 逐条口述部署任务；启动后自己扫描目录：

1. 扫描 `pm/requirements/` 中状态为 `testing` 且测试报告通过的需求
2. 扫描 `pm/bugs/` 中状态为 `fixed` 且测试报告通过的 Bug
3. 确认 `pm/test_reports/` 中有对应的通过报告
4. 执行部署

## 工作步骤
1. 读取 `pm/agents/PROTOCOL.md`
2. 扫描 `pm/requirements/*.md` 和 `pm/bugs/*.md`，找出待发布项
3. 检查 `pm/test_reports/` 确认对应测试报告已通过
4. 执行部署流程：
   - 拉取目标分支（master / release）
   - 构建/编译（如有需要）
   - 部署到测试环境（staging）
   - 执行冒烟测试
   - 部署到生产环境（production）
5. 更新状态：
   - 需求：`testing -> deployed`
   - Bug：`fixed -> deployed`
6. 记录发布日志到 `pm/deploy/YYYY-MM-DD-deploy.md`

## 部署流程（默认）
```
1. git checkout master && git pull
2. 构建（如有需要）：python setup.py build / npm run build
3. 部署到 staging：执行部署脚本
4. 冒烟测试：curl API 健康检查 / 运行基础测试
5. 部署到 production：执行生产部署脚本
6. 验证：确认服务正常运行
```

## 回滚流程
- 部署后 30 分钟内发现问题 → 立即回滚到上一个稳定版本
- 回滚命令：`git revert HEAD` + 重新部署
- 记录回滚原因到 `pm/deploy/ROLLBACK.md`

## 禁止事项
- 不要部署未通过测试的代码
- 不要跳过冒烟测试
- 不要在生产环境直接改代码
- 不要在非发布窗口部署（紧急修复除外）
