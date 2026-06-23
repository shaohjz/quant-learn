# Bug Report - 数据严重滞后 + BaoStock 连接失败

**创建时间**: 2026-06-23 19:40
**发现人**: data-agent（每日数据检查）
**优先级**: 🔴 P0（阻塞交易决策）

---

## Bug 1：行情数据严重滞后（最新仅到 2026-06-16）

### 描述
全部35只股票的 CSV 行情数据最新日期为 **2026-06-16**（周一），缺失：
- 2026-06-19（周四）
- 2026-06-20（周五）  
- 2026-06-22（周一）
- 2026-06-23（周二，今天）

sim_daily_nav 最新到 2026-06-19，也滞后。

### 影响
- 策略信号基于过期数据，可能产生错误交易信号
- 回测结果不准确
- 实盘模拟与真实市场脱节

### 根因分析
1. `fetch_all_stocks.py` 未被定时任务自动调用（无 cron 或调度）
2. 手动运行 `fetch_all_stocks.py` 时 BaoStock 连接失败，无法补数据

### 修复建议
1. 增加每日 16:30 自动数据拉取定时任务
2. 增加多数据源冗余（Tushare 作为 BaoStock 的备份）
3. 数据拉取失败时发送告警

---

## Bug 2：BaoStock 连接失败（WinError 10054）

### 描述
运行 `fetch_all_stocks.py` 或手动 `bs.login()` 时，报：
```
WinError 10054 远程主机强迫关闭了一个现有的连接
error_code: 10002007 error_msg: 网络接收错误
```

### 复现步骤
```bash
cd C:\Users\Administrator\.openclaw\workspace\quant-learn
python -c "import baostock as bs; lg = bs.login(); print(lg.error_msg); bs.logout()"
```

### 环境
- OS: Windows 10 (10.0.26200)
- Python: 3.14
- baostock: 已安装（import 成功）
- 网络: 无法访问外网（urllib 超时）

### 根因分析
内网环境可能无法访问 BaoStock 的对外服务器（http://api.baostock.com），被网络策略阻断。

### 修复建议
1. 检查内网是否有 BaoStock 代理或镜像
2. 切换到内网可访问的数据源：
   - **Tushare**（需要 token，但内网可能可访问）
   - **AKShare**（已移除，因连续7天不可用）
   - **QMT 本地数据源**（如果已配置）
3. 在 `scripts/data_source_manager.py` 中增加数据源健康检查 + 自动切换

---

## Bug 3（衍生）：无数据入库定时任务

### 描述
当前数据拉取完全依赖手动运行 `fetch_all_stocks.py`，无自动化调度。

### 修复建议
在 OpenClaw cron 中增加每日 16:30 的数据拉取任务：
```json
{
  "name": "daily-data-fetch",
  "schedule": { "kind": "cron", "expr": "30 16 * * 1-5", "tz": "Asia/Shanghai" },
  "payload": { "kind": "agentTurn", "message": "运行 fetch_all_stocks.py 更新今日行情数据" },
  "sessionTarget": "isolated"
}
```

---

## 处置记录

| 时间 | 操作 | 结果 |
|------|------|------|
| 2026-06-23 19:36 | 手动运行 `fetch_all_stocks.py` | BaoStock 连接失败 |
| 2026-06-23 19:40 | 创建此 Bug 报告 | - |
| 2026-06-23 19:40 | 写数据日报到 `pm/data/2026-06-23-data.md` | ✅ 完成 |

---

## 下一步

- [ ] 确认内网是否可访问 BaoStock 服务器（check network policy）
- [ ] 配置 Tushare token 作为备用数据源
- [ ] 设置每日 16:30 数据拉取 cron 任务
- [ ] 数据拉取失败时发送企业微信告警
