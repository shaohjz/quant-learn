# REQ-044 实施文档：职业理财经理 Agent

## 功能概述
每天收盘后（15:30）自动运行，从专业角度复盘当日操作，分析仓位健康度，诊断策略表现，主动提出改进需求，推送日报到企微。

## 实施状态
- ✅ 核心功能已实现 (`scripts/pm_finance_manager.py`)
- ✅ 日报生成逻辑已完成
- ✅ 自动创建改进需求功能已完成
- ⚠️ 企微 Webhook 待配置
- ⚠️ Cron 定时任务待配置

## 配置文件
### config.yaml
```yaml
notify:
  wecom_webhook: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY_HERE'
```

## 使用方法

### 手动运行
```bash
# 指定日期
python scripts/pm_finance_manager.py 2026-06-15

# 使用今天日期
python scripts/pm_finance_manager.py
```

### 自动运行（Cron）
建议使用 cron 工具配置定时任务：
- 时间：每个交易日 15:30
- 命令：`python scripts/pm_finance_manager.py`

## 输出
1. **日报文件**：`output/finance_manager/YYYY-MM-DD.md`
2. **企微推送**：Markdown 格式日报
3. **自动创建需求**：直接写入 `data/pm.db` 的 `tasks` 表

## 下一步
1. 在企微群里添加自定义机器人，获取 Webhook URL
2. 将 Webhook URL 配置到 `config.yaml` 的 `notify.wecom_webhook`
3. 配置 cron 定时任务（每日 15:30 运行）
4. 测试完整流程

## 测试记录
- 2026-06-16 00:05: 成功生成 2026-06-15 日报，保存至 `output/finance_manager/2026-06-15.md`
- 数据库表 `strategy_shadow_signals` 不存在，已优雅处理（跳过执行率分析）
