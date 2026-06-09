# Bug: 数据自动补录失败 - AKShare 接口连接中断

**Bug ID**: DATA-20260609-001  
**创建时间**: 2026-06-09 19:40  
**优先级**: 🔴 高（数据滞后 18 天，影响策略信号）  
**状态**: Open  
**报告人**: 数据 Agent (data-agent)

---

## 问题描述

自动补数据任务（`scripts/backfill_data.py`）执行时，AKShare `stock_zh_a_hist` 接口全部返回连接错误：

```
Connection aborted: RemoteDisconnected('Remote end closed connection without response')
```

影响范围：全部 31 只股票，无法自动补录 2026-05-23 至今的数据。

## 影响

- 数据最后日期：**2026-05-22**（距今 **18 天**）
- 所有依赖最新数据的策略信号已失效
- 回测和模拟交易使用过期数据

## 根因分析

1. **AKShare 服务端限流**：短时间内请求 31 只股票触发频率限制
2. **数据源（东方财富）反爬**：AKShare 爬取 eastmoney 接口被封禁
3. **缺少重试机制**：当前脚本无退避重试，失败即跳过

## 复现步骤

```bash
cd C:\Users\Administrator\.openclaw\workspace\quant-learn
python scripts/backfill_data.py
```

## 建议修复方案

### 方案 A：增加重试 + 延迟（短期）
- 在 `fetch_stock_data` 中加入 `tenacity` 重试（3次，指数退避）
- 请求间隔增加到 2-5 秒
- 预计修复时间：1 小时

### 方案 B：切换数据源（中期）
- 接入 **BaoStock**（已在 `fetch_data.py` 有备选实现）
- 或接入 **Tushare**（需 token）
- 或接入 **QMT/vnpy** 本地数据源
- 预计修复时间：半天

### 方案 C：手动补录（紧急临时）
- 手动从交易软件导出 CSV
- 运行合并脚本

## 附加信息

- AKShare 版本：1.18.60
- 网络检查：eastmoney.com TCP 80 可达（网络正常）
- 错误类型：`RemoteDisconnected`（服务端主动断开）
- 数据文件最后日期：2026-05-22

---

**下一步**: 分配工程师修复，或先手动补录关键股票数据。
