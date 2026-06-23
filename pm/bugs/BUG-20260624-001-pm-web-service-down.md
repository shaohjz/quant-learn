# BUG-20260624-001: PM Web 服务（8080）频繁挂掉

## 基本信息
- **Bug ID**: BUG-20260624-001
- **标题**: PM Web 服务（8080端口）频繁挂掉，需要自动恢复
- **状态**: deployed
- **优先级**: P0
- **创建时间**: 2026-06-24
- **创建人**: PM Agent

## 问题描述
`http://21.214.59.210:8080` 和 `http://21.214.59.210:8080/pm` 经常无法访问，返回 000 状态码（服务未启动）。

## 根因分析
- Web 服务（`web/app.py`，Flask 应用）没有守护进程/自动重启机制
- 没有运维 Agent 每天巡检服务状态
- 当前 ops-agent-daily cron 在 19:00 运行，但 PM 服务可能在任意时间挂掉

## 修复方案
1. **✅ 短期修复**：注册 `PM_Watchdog` Windows 计划任务（每5分钟触发），调用增强版 `pm_watchdog.py` 自动重启
2. **长期修复**：将 PM Web 服务转为 Windows 服务或使用 PM2 管理（待排期）

## 修复内容

### 1. 注册 Windows 计划任务 `PM_Watchdog`
```
schtasks /Create /TN "PM_Watchdog" /TR "C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts\pm_watchdog_runner.bat" /SC MINUTE /MO 5 /F
```
每5分钟自动运行看门狗脚本。

### 2. 增强 `scripts/pm_watchdog.py`
- 文件锁防止并发运行
- 修复 `PYTHONIOENCODING` 拼写错误
- 重启前等待端口释放（避免 Address already in use）
- 重启后多次健康检查（3次重试）
- 重启失败时推送企微告警
- 详细日志（含 PID、端口、响应码）

## 状态历史
- 2026-06-24: 创建 Bug，状态 `open`
- 2026-06-24 01:05: 修复完成，状态 `fixed`
