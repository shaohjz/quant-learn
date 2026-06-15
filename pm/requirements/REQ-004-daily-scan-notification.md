# REQ-004: 每日扫描通知

## 基本信息
- **需求 ID**: REQ-004
- **标题**: 每日扫描通知
- **状态**: deployed
- **优先级**: P1
- **创建时间**: 2026-06-09
- **创建人**: PM Agent
- **指派给**: 研发 Agent

## 背景
每日扫描结果需要自动推送到企微群，方便及时查看。

## 目标
实现每日扫描完成后自动发送企微通知。

## 详细需求
1. **通知时机**：
   - 盘前扫描（morning_scanner）完成后通知
   - 盘后复盘（daily_review）完成后通知

2. **通知内容**：
   - 信号摘要（买入/卖出/持仓）
   - 关注池更新

3. **通知方式**：
   - 企微群机器人 webhook
   - Markdown 格式，支持 @all

## 验收标准
1. ✅ `sim/notifier.py` 有 `send_text`、`send_markdown`、`notify_daily_report`、`notify_signals`
2. ✅ `morning_scanner.py` 集成 notifier
3. ✅ `daily_review.py` 集成 notifier
4. ✅ 企微 webhook 配置读取 `_wecom_webhook_url()`

## 相关数据文件
- `sim/notifier.py`
- `scripts/morning_scanner.py`
- `scripts/daily_review.py`

## 状态历史
- 2026-06-09: 创建需求，状态 `pending`
- 2026-06-10: 实现完成，状态 `testing`
- 2026-06-15 17:00: QA 验收通过（测试报告 TEST-2026-06-15-002），状态 `done`
- 2026-06-15 18:37: 部署到 production，状态 `deployed`
