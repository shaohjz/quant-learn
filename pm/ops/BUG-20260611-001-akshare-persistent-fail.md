# BUG-20260611-001: AKShare 行情源持续失败（第3天）

**创建时间：** 2026-06-11 19:06  
**严重等级：** S1  
**状态：** fixed  
**修复时间：** 2026-06-12  
**影响：** 实时行情信号生成依赖 AKShare，主源失效迫使使用 BaoStock 备选（延迟较高）

---

## 描述

AKShare 行情接口连续 3 天（2026-06-09 ~ 2026-06-11）连接失败，错误如下：

```
requests.exceptions.ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
```

失败接口：
- `ak.stock_zh_a_spot_em()`
- `ak.stock_zh_a_hist()`
- `ak.stock_individual_info_em()`

## 复现步骤

```python
import akshare as ak
df = ak.stock_zh_a_spot_em()  # 必现
```

## 当前缓解措施

`data/fetch_data.py` 已内置 BaoStock 自动切换，日线数据拉取正常。

## 建议修复

1. **升级 AKShare**：`pip install -U akshare`
2. **增加 HTTP Proxy**：AKShare 可能被网络策略限制
3. **切换主源**：将 BaoStock 或 Tushare 设为主源，AKShare 降级为备选
4. **多源负载均衡**：同时配置 2+ 数据源，任一失败自动切换

## 修复记录（2026-06-12）

### 根因确认
1. **AKShare 服务端限流/封禁**：连续 3 天连接失败，`RemoteDisconnected`
2. **单数据源依赖**：`realtime_price_gateway.py` 只支持单一数据源，AKShare 失败时无自动切换
3. **`fetch_data.py` 已有 BaoStock 备选**：日线数据获取已支持多源，但实时行情网关未同步

### 修复方案
重写 `gateways/realtime_price_gateway.py`：

1. **多数据源自动切换**：
   - 数据源优先级：`["baostock", "akshare"]`（BaoStock 主源，AKShare 备选）
   - 任一数据源失败时自动切换到下一个
   - 数据源恢复时自动标记可用

2. **模块级函数**：
   - `_get_baostock_price()`：BaoStock 获取收盘价
   - `_get_akshare_price()`：AKShare 获取收盘价
   - 不再依赖 `self.ak` 等实例变量，避免导入时失败

3. **`gateways/__init__.py`**：
   - 将 `QmtGateway` 导入改为可选（try/except），避免 vnpy 未安装时影响其他模块导入

### 验证结果
```bash
python -c "
from gateways.realtime_price_gateway import RealtimePriceGateway
from gateways import RealtimePriceGateway
gateway = RealtimePriceGateway(sources=['baostock', 'akshare'])
price = gateway.get_realtime_price('600519')
print(f'600519 价格: {price}')
print(f'数据源状态: {gateway.get_source_status()}')
"
# 输出：
# login success!
# logout success!
# 600519 价格: 1279.0
# 数据源状态: {'baostock': True, 'akshare': True}
```

### 状态历史
| 时间 | 状态 | 说明 |
|------|------|------|
| 2026-06-11 19:06 | open | Bug 创建 |
| 2026-06-12 15:45 | fixed | 多数据源自动切换已实现并自测通过 |
