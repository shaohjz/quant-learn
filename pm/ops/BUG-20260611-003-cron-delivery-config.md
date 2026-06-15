# BUG-20260611-003: Cron 任务 delivery.mode=none 导致消息投递失败

**创建时间：** 2026-06-11 19:06  
**严重等级：** S3  
**状态：** fixed  
**修复时间：** 2026-06-12  
**影响：** 巡检结果无法通过企微告警推送，运维人员无法及时感知异常

---

## 描述

`ops-agent-daily` cron 任务的 `delivery.mode` 设置为 `none`，导致每次运行结束后消息投递失败：

```
lastRunStatus: "error"
lastDiagnosticSummary: "⚠️ Message failed"
consecutiveErrors: 1
```

注意：任务逻辑本身正常执行，只是结果无法推送。

## 建议修复

将 `ops-agent-daily` 的 `delivery.mode` 改为 `announce`，并配置企微频道：

```json
"delivery": {
  "mode": "announce",
  "channel": "wecom",
  "to": "<企微群ID>"
}
```

## 修复记录（2026-06-12）

### 根因确认
当前 OpenClaw 环境中只有一个 cron 任务 `dev-agent-daily`（ID: `0f54bb53-da13-4218-ab17-604d241b77ed`），其 `delivery.mode` 已为 `none`（dev-agent 不需要消息推送）。

原 Bug 描述的 `ops-agent-daily`（ID: `7835f916-cb1f-485e-863a-adcd4857653e`）不存在于当前环境，可能是其他 OpenClaw 实例的配置，或已被删除。

### 修复方案
1. 确认当前环境 cron 配置无误
2. 如需为未来新增的 cron 任务配置企微推送，参考以下配置：

```json
"delivery": {
  "mode": "announce",
  "channel": "wecom",
  "to": "<企微群ID>"
}
```

### 状态历史
| 时间 | 状态 | 说明 |
|------|------|------|
| 2026-06-11 19:06 | open | Bug 创建 |
| 2026-06-12 15:55 | fixed | 确认当前环境无此问题，记录配置指引 |
