# 如何配置企微群机器人 Webhook

## 步骤（请先在企微群里操作）

1. 打开企微群聊
2. 点击右上角 `···` → `群机器人` → `添加机器人`
3. 给机器人起个名字（如"量化警报"）
4. 添加成功后会得到一个 Webhook URL，类似：
   ```
   https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   ```

## 配置到系统

拿到 Webhook URL 后，有两种方式配置：

### 方式一：直接修改 config.yaml（推荐）

编辑 `config.yaml`，找到这一行：

```yaml
notify:
  wecom_webhook: ''  # 请在企微群里添加自定义机器人，获取 Webhook URL 并替换此处
```

把 `''` 替换成你的 Webhook URL：

```yaml
notify:
  wecom_webhook: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY_HERE'
```

保存后，重启定时任务或等待下次执行即可生效。

### 方式二：通过环境变量（临时测试）

```bash
cd C:\Users\Administrator\.openclaw\workspace\quant-learn
set WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY_HERE
python scripts/portfolio_alert.py
```

## 验证配置

配置完成后，手动运行一次测试：

```bash
cd C:\Users\Administrator\.openclaw\workspace\quant-learn
python scripts\portfolio_alert.py
```

如果看到日志里有：
```
webhook 推送成功
```

说明配置成功！

## 故障排查

### 问题1：webhook 返回 `errcode: 93000`
→ Webhook URL 错误，请重新从企微群复制

### 问题2：webhook 返回 `errcode: 88888`
→ IP 不在白名单，需要在企微群机器人设置里添加服务器 IP

### 问题3：完全没看到 webhook 相关日志
→ 检查 `config.yaml` 中的缩进是否正确（`notify` 下一级是 `wecom_webhook`）
