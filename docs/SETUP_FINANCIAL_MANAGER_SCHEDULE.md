# 理财经理 Agent 定时任务设置指南

## 功能说明
`financial_manager_agent.py` 会在每个交易日 15:30 自动运行，生成理财经理日报并推送到企微群。

## 设置步骤

### 1. 配置企微 Webhook
编辑 `config.yaml`，设置正确的 Webhook URL：
```yaml
notify:
  wecom_webhook: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY_HERE'
```

### 2. 创建 Windows 定时任务
以管理员身份运行 CMD，执行以下命令：

```batch
schtasks /create /tn "QuantLearn-理财经理日报" /tr "C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts\run_financial_manager_daily.bat" /sc daily /st 15:30
```

### 3. 验证任务已创建
```batch
schtasks /query /tn "QuantLearn-理财经理日报"
```

### 4. 手动测试运行
```batch
schtasks /run /tn "QuantLearn-理财经理日报"
```

## 日志查看
- 脚本运行日志：查看脚本输出的 INFO/ERROR 信息
- 生成的日报：`docs/reviews/YYYY-MM-DD_financial_manager.md`
- 任务执行历史：`schtasks /query /tn "QuantLearn-理财经理日报" /v /fo list`

## 故障排查
1. **Webhook 未配置**：编辑 `config.yaml` 设置 `notify.wecom_webhook`
2. **任务未运行**：检查 Windows Task Scheduler 中的任务状态
3. **Python 路径问题**：确保 `scripts/run_financial_manager_daily.bat` 中的路径正确

## 手动运行
如果不想设置定时任务，也可以手动运行：
```batch
cd C:\Users\Administrator\.openclaw\workspace\quant-learn
python scripts/financial_manager_agent.py
```
