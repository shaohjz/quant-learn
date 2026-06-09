# Bug Report — AkShare 行情源连接失败

**Bug ID：** BUG-20260609-001  
**创建时间：** 2026-06-09 19:06  
**发现方式：** 每日运维巡检（ops-agent-daily）  
**严重等级：** S1（生产影响 — 行情数据无法获取，信号生成中断）

---

## 问题描述

`gateways/realtime_price_gateway.py` 使用 AkShare 获取实时行情，所有 AkShare API 调用均返回连接错误：

```
('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
```

影响范围：
- `RealtimePriceGateway.get_realtime_price()` — 持续失败
- `data/cache/` 最新数据停留在 2026-06-05 09:31（距今 6332 分钟）
- `data/universe_cache.json` 过期 15 天
- `data/sector_cache.json` 过期 8 天

---

## 复现步骤

```python
from gateways.realtime_price_gateway import RealtimePriceGateway
gw = RealtimePriceGateway(source='akshare')
price = gw.get_realtime_price('600519')  # → None，报连接错误
```

---

## 根因分析

- AkShare 后端依赖东方财富（`push2.eastmoney.com`）API
- 远端服务器主动关闭连接（`RemoteDisconnected`）
- 可能原因：
  1. 服务器端限流/IP 封禁
  2. AkShare 版本（1.18.60）过旧，接口已变更
  3. 网络代理/防火墙阻断

---

## 建议修复

1. **立即：** 安装 Tushare，配置 token，切换 `config.yaml` 中行情源为 tushare
2. **备选：** 启用 QMT 网关（`gateways/qmt_gateway.py`）作为本地行情源
3. **长期：** 增加多数据源熔断降级（AkShare 失败 → 自动切换 Tushare → QMT）

---

## 状态

- [ ] 待修复
- [ ] 已修复
- [x] 已确认

**指派人：** 待定  
**发现人：** ops-agent-daily
