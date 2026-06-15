# Bug: 数据自动补录失败 - AKShare 接口连接中断

**Bug ID**: DATA-20260609-001  
**创建时间**: 2026-06-09 19:40  
**优先级**: 🔴 高（数据滞后 18 天，影响策略信号）  
**状态**: deployed
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

## 修复记录（2026-06-10）

### 根因确认
1. **AKShare 服务端限流**：短时间内请求 31 只股票触发频率限制，导致 `RemoteDisconnected`
2. **缺少重试机制**：原脚本无退避重试，失败即跳过
3. **数据源单一**：仅依赖 AKShare，无备选方案

### 修复方案
重写 `scripts/backfill_data.py`，实施以下改进：

1. **BaoStock 作为主力数据源**：
   - 登录/登出机制，每次请求独立认证
   - 前复权数据（`adjustflag='2'`）
   - 股票代码自动转换（`600519` → `sh.600519`，`000333` → `sz.000333`）

2. **AKShare 作为备选数据源**：
   - BaoStock 失败后自动切换
   - 统一列名映射

3. **指数退避重试**：
   - 最大重试 3 次
   - 延迟：`2^attempt + random(0,1)` 秒

4. **合并类型安全**：
   - `pd.to_datetime()` 统一 `date` 列类型，避免 `Timestamp vs str` 比较错误
   - `drop_duplicates(subset=['date'])` 去重

5. **日志系统**：
   - 输出到 `output/backfill.log`（可追溯）
   - 控制台实时显示进度

### 验证结果
```
找到 31 个股票文件
完成: 成功 31, 失败 0
```

所有 31 只股票数据已从 `2026-05-22` 补全至 `2026-06-09`（共 12 个交易日）。

### 状态历史
| 时间 | 状态 | 说明 |
|------|------|------|
| 2026-06-09 19:40 | open | Bug 创建 |
| 2026-06-10 06:10 | fixed | BaoStock 主力 + AKShare 备选，重试机制，全量补录成功 |
| 2026-06-11 18:42 | deployed | 部署到 production |

---

**下一步**: 监控今日（2026-06-10）收盘后数据是否能正常自动补录。如 BaoStock 也失败，考虑接入 QMT 本地数据源。
| 2026-06-15 18:37 | deployed | 部署到 production |
