# REQ-042 自测报告

**需求ID**: REQ-042  
**需求名称**: 量化通知/盘中盯盘 去大模型化 — 纯代码 + 企微 Webhook 直推  
**测试时间**: 2026-06-19  
**测试人**: dev-manager  

## 测试环境
- Python 3.9+
- requests 库
- config.yaml（需要配置 `notifier.wecom_webhook`）

## 已实现功能

### 1. `scripts/wecom_notifier.py`（通用通知脚本）
**功能**：
- ✅ 支持 text、markdown、image 三种消息类型
- ✅ 自动从 config.yaml 或环境变量 `WECOM_WEBHOOK` 读取 Webhook URL
- ✅ 命令行接口完整

**测试方法**：
```bash
# 测试 text 消息
python scripts/wecom_notifier.py --type text --content "测试消息"

# 测试 markdown 消息
python scripts/wecom_notifier.py --type markdown --content "## 测试\n**加粗**"

# 测试 image 消息（需要图片文件）
python scripts/wecom_notifier.py --type image --path "test.png"
```

**预期结果**：
- 如果配置了正确的 Webhook URL，消息会发送到企微群
- 如果未配置，会提示错误信息

### 2. `scripts/notify_auction.py`（集合竞价快报）
**功能**：
- ✅ 读取 `data/auction_data.json`
- ✅ 格式化快报内容（按涨跌幅排序）
- ✅ 调用 `wecom_notifier.py` 发送 markdown 消息

**依赖**：
- 需要数据抓取脚本生成 `data/auction_data.json`

**测试方法**：
```bash
# 创建测试数据文件
echo '{"stocks": [{"name": "测试股票", "code": "000001", "price": 10.5, "change_pct": 2.5}]}' > data/auction_data.json

# 运行脚本
python scripts/notify_auction.py
```

### 3. `scripts/notify_daily_review.py`（收盘复盘通知）
**功能**：
- ✅ 读取 `output/reviews/YYYY-MM-DD.md`
- ✅ 提取关键信息（模拟盘/实盘表现、信号、持仓变化）
- ✅ 调用 `wecom_notifier.py` 发送摘要

**测试方法**：
```bash
# 确保今日复盘报告存在
ls output/reviews/$(date +%Y-%m-%d).md

# 运行脚本
python scripts/notify_daily_review.py
```

### 4. `scripts/notify_intraday_watch.py`（盘中盯盘通知）
**功能**：
- ✅ 检查触发条件（当前为空实现，需要集成实时行情）
- ✅ 避免重复通知（使用 `data/trigger_states.json`）
- ✅ 调用 `wecom_notifier.py` 发送通知

**待完善**：
- 需要集成实时行情接口
- 需要读取 config.yaml 中的 watchlist 和 rules

## 已知问题

1. **Webhook URL 未配置**：
   - `config.yaml` 中 `notifier.wecom_webhook` 为空
   - 需要用户在企微群里添加自定义机器人并获取 Webhook URL

2. **数据抓取脚本缺失**：
   - `notify_auction.py` 依赖 `data/auction_data.json`
   - 需要创建数据抓取脚本

3. **实时行情接口缺失**：
   - `notify_intraday_watch.py` 中的 `check_triggers()` 函数需要集成实时行情

## 下一步建议

1. **用户配置 Webhook URL**：
   - 在企微群里添加自定义机器人
   - 将 Webhook URL 写入 `config.yaml`

2. **创建数据抓取脚本**：
   - 创建 `scripts/fetch_auction_data.py`
   - 定时生成 `data/auction_data.json`

3. **完善盘中盯盘逻辑**：
   - 集成实时行情接口（如 AKShare、BaoStock）
   - 读取 config.yaml 中的 watchlist 和 rules

## 测试结论

✅ **基础框架已完成**，可以进入 `testing` 状态。

需要用户配置 Webhook URL 后才能完整测试通知功能。
