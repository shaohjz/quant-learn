# 企业微信 Webhook 配置指南

## 概述
`notify_intraday.py` 脚本通过企业微信 Webhook 推送盘中盯盘报告。需要先配置 Webhook URL 才能正常推送。

## 配置步骤

### 1. 获取企业微信 Webhook URL

1. 打开企业微信，进入需要推送消息的群聊
2. 点击群聊右上角的 `...` 菜单
3. 选择 `添加群机器人`
4. 设置机器人名称和头像
5. 点击 `添加` 完成创建
6. 复制生成的 Webhook URL（格式：`https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...`）

### 2. 配置到 config.yaml

编辑 `config.yaml` 文件，找到 `notify:` 部分，将 Webhook URL 替换为你复制的 URL：

```yaml
notify:
  wecom_webhook: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY_HERE'
```

### 3. 测试配置

运行测试命令，验证 Webhook 是否配置正确：

```bash
cd C:\Users\Administrator\.openclaw\workspace\quant-learn
python wecom_webhook.py
```

如果配置正确，你应该会看到：
```
Webhook URL: 已配置
推送结果: 成功
```

同时，企业微信群里会收到一条测试消息。

### 4. 运行盘中盯盘脚本

配置完成后，可以运行盘中盯盘脚本测试推送功能：

```bash
# 正常推送（需要盘中交易时段）
python scripts/notify_intraday.py

# 强制运行（忽略交易时段检查）
python scripts/notify_intraday.py --force

# 只打印不推送（测试用）
python scripts/notify_intraday.py --dry-run
```

## 故障排除

### 问题1：Webhook URL 未配置

**错误信息**：`Webhook URL: 未配置` 或 `未找到企业微信 Webhook URL 配置`

**解决方法**：
1. 检查 `config.yaml` 中 `notify.wecom_webhook` 是否正确配置
2. 确保 Webhook URL 是字符串格式，用单引号或双引号包裹
3. 运行 `python wecom_webhook.py` 验证配置

### 问题2：推送失败

**错误信息**：`❌ 企业微信推送失败` 或 `推送结果: 失败`

**解决方法**：
1. 检查 Webhook URL 是否正确（复制完整，没有多余空格）
2. 检查企业微信机器人是否被禁用或删除
3. 检查网络连接是否正常
4. 查看返回的错误信息（`errcode` 和 `errmsg`）

### 问题3：消息格式不正确

**现象**：企业微信收到消息，但格式混乱或显示不正常

**解决方法**：
1. 检查消息内容是否符合企业微信 Markdown 格式规范
2. 避免消息内容过长（企业微信有长度限制）
3. 测试简单的 Markdown 消息，逐步增加复杂度

## 高级配置

### 自定义推送时间

脚本默认在盘中交易时段运行（9:30-11:30, 13:00-15:00）。可以通过修改 `cron` 任务来自定义推送时间。

### 推送其他类型消息

`wecom_webhook.py` 支持推送以下类型消息：
- `push_markdown()`: 推送 Markdown 格式消息（默认）
- `push_text()`: 推送纯文本格式消息

可以根据需要修改 `notify_intraday.py` 中的推送逻辑。

## 安全注意事项

1. **保护 Webhook URL**：Webhook URL 包含密钥，不要公开分享或提交到代码仓库
2. **定期更新**：如果 Webhook URL 泄露，可以在企业微信中重置机器人密钥
3. **权限控制**：只有群管理员可以添加/删除群机器人

## 参考资料

- 企业微信机器人文档：https://developer.work.weixin.qq.com/document/path/91770
- Markdown 格式规范：https://developer.work.weixin.qq.com/document/path/91770#markdown%E6%A0%BC%E5%BC%8F
