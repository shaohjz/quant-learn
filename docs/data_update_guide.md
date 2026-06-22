# 数据更新操作指南

## 当前状态
- 数据最新日期: 2026-06-16 / 2026-06-18
- 当前日期: 2026-06-22
- 需要补充: 2026-06-19 ~ 2026-06-22 的数据

## 快速补充方案

### 方案1: 使用 existing 脚本（推荐）
```bash
cd C:\Users\Administrator\.openclaw\workspace\quant-learn
python data/fetch_data.py
```

**注意**: 需要先修复 `data/fetch_data.py` 的bug（缺少`health_check`方法）

### 方案2: 使用数据源管理器直接获取
```python
from scripts.data_source_manager import DataSourceManager
dsm = DataSourceManager()

# 获取单个股票数据
df = dsm.fetch_data('000858', '20260619', '20260622', adjust='qfq')

# 追加到现有文件
df.to_csv('data/000858.csv', mode='a', header=False, index=False)
```

### 方案3: 使用 curl 直接调用东方财富API
```bash
# 获取日线数据
curl -s "http://push2his.eastmoney.com/api/qt/stock/kline/get?secid=0.000858&fields1=f1,f2,f3,f4,f5&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1&beg=20260619&end=20260622" > temp.json
```

## 推荐操作流程

1. **修复Bug**: 完善 `data/fetch_data.py` 脚本
2. **手动补充**: 运行修复后的脚本
3. **验证数据**: 运行 `python scripts/data_integrity_check.py`
4. **设置定时**: 添加每日15:30自动运行任务

## 定时任务设置（Windows）

使用任务计划程序:
- 触发器: 每日 15:30
- 操作: 运行 `python data/fetch_data.py`
- 条件: 仅在网络可用时运行

或使用 OpenClaw cron:
```
设置每日15:30运行数据更新脚本
```

## 监控告警

在数据日报中添加检查:
- 如果最新数据日期 < 当前日期 - 1（交易日）, 发送告警

---

**创建时间**: 2026-06-22 19:45  
**创建者**: data-agent
