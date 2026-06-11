# 实时行情API集成文档

## 概述

本项目现已集成实时行情API功能，支持从多个数据源获取股票实时/历史收盘价，用于更新模拟持仓、策略回测等场景。

## 功能特性

- ✅ 支持多个数据源：AkShare（免费）、Tushare（需注册）
- ✅ 获取单只/批量股票实时价格
- ✅ 获取指定日期的历史收盘价
- ✅ 自动更新数据库中的持仓价格
- ✅ 错误处理与日志记录

## 快速开始

### 1. 安装依赖

```bash
# 安装 AkShare（免费，无需注册）
pip install akshare

# 或安装 Tushare（需注册获取token）
pip install tushare
```

### 2. 基本用法

```python
from gateways.realtime_price_gateway import RealtimePriceGateway

# 使用 AkShare（免费）
gateway = RealtimePriceGateway(source="akshare")

# 获取单只股票实时价格
price = gateway.get_realtime_price("600330")  # 浙江鼎力
print(f"实时价格: {price:.2f}元")

# 获取指定日期收盘价
historical_price = gateway.get_realtime_price("600330", "20240531")
print(f"历史收盘价: {historical_price:.2f}元")

# 批量获取
symbols = ["600330", "000001", "600519"]
prices = gateway.get_batch_prices(symbols)
```

### 3. 更新数据库

```python
# 自动更新数据库中所有持仓的实时价格
gateway.update_database_with_realtime_prices()
```

## API 详解

### `RealtimePriceGateway` 类

#### 初始化参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `source` | str | `"akshare"` | 数据源，可选 `"akshare"` 或 `"tushare"` |
| `token` | str | `None` | Tushare token（使用 Tushare 时必填） |

#### 主要方法

##### `get_realtime_price(symbol, trade_date=None)`
获取股票收盘价

**参数：**
- `symbol` (str): 股票代码，如 `"600330"`
- `trade_date` (str, optional): 交易日期，格式 `"20240101"`，默认为最新

**返回：**
- `float` 或 `None`: 收盘价，无数据返回 `None`

**示例：**
```python
# 获取实时价格
price = gateway.get_realtime_price("600330")

# 获取历史价格
price = gateway.get_realtime_price("600330", "20240531")
```

##### `get_batch_prices(symbols, trade_date=None)`
批量获取股票收盘价

**参数：**
- `symbols` (List[str]): 股票代码列表
- `trade_date` (str, optional): 交易日期

**返回：**
- `Dict[str, Optional[float]]`: {股票代码: 收盘价} 字典

**示例：**
```python
prices = gateway.get_batch_prices(["600330", "000001", "600519"])
# 返回: {"600330": 25.50, "000001": 12.30, "600519": 1680.00}
```

##### `update_database_with_realtime_prices(db_path=None)`
用实时行情更新数据库中的持仓价格

**参数：**
- `db_path` (str, optional): 数据库路径，默认为 `data/sim_live_mirror.db`

**说明：**
自动从数据库中读取所有持仓股票，获取其实时价格并更新 `sim_positions` 表。

## 数据源对比

| 特性 | AkShare | Tushare |
|------|---------|---------|
| 费用 | 免费 | 免费（需注册） |
| 注册 | 不需要 | 需要（https://tushare.pro） |
| 频率限制 | 较宽松 | 有访问频率限制 |
| 数据完整性 | 良好 | 非常好 |
| 推荐场景 | 个人项目、快速原型 | 专业量化、高频访问 |

## 使用示例

完整示例代码见：`examples/realtime_price_example.py`

运行示例：
```bash
cd quant-learn
python examples/realtime_price_example.py
```

## 集成到现有系统

### 1. 在策略中使用

```python
# strategies/your_strategy.py
from gateways.realtime_price_gateway import RealtimePriceGateway

class YourStrategy:
    def __init__(self):
        self.price_gateway = RealtimePriceGateway(source="akshare")
    
    def before_trade(self, symbol):
        # 获取最新价格用于决策
        current_price = self.price_gateway.get_realtime_price(symbol)
        # ... 策略逻辑
```

### 2. 定时更新持仓价格

可以配合 cron 或调度系统，每日收盘后更新持仓价格：

```python
# scripts/update_positions_daily.py
from gateways.realtime_price_gateway import RealtimePriceGateway
from datetime import datetime

def update_daily():
    gateway = RealtimePriceGateway(source="akshare")
    gateway.update_database_with_realtime_prices()
    print(f"{datetime.now()} - 持仓价格更新完成")

if __name__ == "__main__":
    update_daily()
```

## 错误处理

所有方法都包含异常处理，会自动记录日志：

```python
import logging

# 启用日志
logging.basicConfig(level=logging.INFO)

gateway = RealtimePriceGateway(source="akshare")
price = gateway.get_realtime_price("600330")
# 如果失败，会记录 ERROR 日志并返回 None
```

## 注意事项

1. **网络依赖**：需要能够访问外网API（AkShare 使用东方财富等公开接口）
2. **交易时间**：非交易时间获取的可能为上一交易日收盘价
3. **频率限制**：避免过于频繁的请求，建议：
   - AkShare：请求间隔 ≥ 0.5秒
   - Tushare：请求间隔 ≥ 0.1秒（免费用户有严格限制）
4. **数据延迟**：免费接口通常有几分钟到几十分钟的延迟

## 扩展开发

### 添加新数据源

继承并扩展 `RealtimePriceGateway` 类：

```python
class EnhancedPriceGateway(RealtimePriceGateway):
    def _get_custom_source_price(self, symbol, trade_date):
        # 实现自定义数据源逻辑
        pass
```

### 添加缓存机制

为避免重复请求，可以添加本地缓存：

```python
from functools import lru_cache

class CachedPriceGateway(RealtimePriceGateway):
    @lru_cache(maxsize=100)
    def get_realtime_price(self, symbol, trade_date=None):
        return super().get_realtime_price(symbol, trade_date)
```

## 相关任务

- ✅ REQ-053: 集成实时行情API获取收盘价（已完成）
- 后续可考虑：添加更多数据源（如新浪财经、腾讯财经等）
- 后续可考虑：添加实时Tick数据支持
- 后续可考虑：添加期货、期权等其他品种支持

## 维护日志

- 2026-06-01: 初始版本，支持 AkShare 和 Tushare
- 创建者：OpenClaw Agent（子任务 PM-Agent-Sub-1）

## 联系方式

如有问题或建议，请联系项目维护者或提交 Issue。