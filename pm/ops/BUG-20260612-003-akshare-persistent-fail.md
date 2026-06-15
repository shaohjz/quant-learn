# Bug 跟踪 — AKShare 主行情源持续不可用（第4天）

## Bug 信息
- **原始 Bug ID**: BUG-20260609-001 / BUG-20260610-001
- **跟踪更新**: 2026-06-12 19:05
- **严重级别**: S1（高优先级）
- **状态**: ❌ 未修复（实际依然失败，先前 `fixed` 标记有误）
- **影响组件**: 数据获取模块（AkShare 行情源）
- **连续失败天数**: **4天**（2026-06-09 至 2026-06-12）

## 当前状态（2026-06-12 19:00 巡检）

| 检查项 | 结果 |
|--------|------|
| AKShare `stock_zh_a_spot_em()` | ❌ `Connection aborted, Remote end closed connection without response` |
| BaoStock 备选 | ✅ 正常登录和查询 |
| 数据更新 | ✅ 收盘数据正常（15:32），通过 BaoStock 获取 |
| 自动恢复尝试 | ❌ 失败（远端问题，非本机） |

## 根因分析（更新）

- AkShare 依赖的东方财富 API（`push2.eastmoney.com`）持续拒绝连接
- 可能原因：
  1. 服务器端对 AKShare 爬虫进行限流/IP 封禁（最可能）
  2. AkShare 版本（1.18.64）过旧，`stock_zh_a_spot_em` 接口已变更
  3. 网络环境变化（代理/防火墙）
- **结论**：本机网络正常，问题在 AkShare 远端或接口变更

## 建议行动（更新）

### 立即（本周内）
1. **切换主源**：将 `realtime_price_gateway.py` 默认 source 改为 `baostock`
2. **升级 AKShare**：`pip install -U akshare`（当前 1.18.64，检查是否有新版本）
3. **增加 Tushare 作为第三备份**（需注册 token）

### 如 AKShare 修复
- 检查 AKShare GitHub Release 是否有相关 Fix
- 验证 `stock_zh_a_spot_em()` 在新版本是否可用

---

## 历史记录

| 日期 | 巡检报告 | 状态 |
|------|---------|------|
| 2026-06-09 | `2026-06-09-ops.md` | 首次发现，创建 BUG-20260609-001 |
| 2026-06-10 | `2026-06-10-ops.md` | 持续失败，创建 BUG-20260610-001（后标记 fixed，不准确） |
| 2026-06-11 | `2026-06-11-ops.md` | 持续失败，报告建议升级为 P1 |
| 2026-06-12 | `2026-06-12-ops.md` | 持续失败（第4天），本题跟踪 |

---

**更新人**: ops-agent-daily  
**下一步**: 如 2026-06-13 仍失败，建议永久切换 BaoStock 为主源，AKShare 降级为备选。
