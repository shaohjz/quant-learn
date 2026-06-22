# Bug: AKShare 数据源持续连接失败

**Bug ID**: BUG-20260616-001  
**创建时间**: 2026-06-16 19:37  
**优先级**: 🟡 中等  
**状态**: ✅ Verified  
**报告人**: 数据 Agent (data-agent)  
**修复人**: dev-agent  
**修复时间**: 2026-06-17 15:31  

---

## 问题描述

数据完整性检查过程中，发现 **AKShare 数据源无法连接**，所有尝试均失败。

### 错误详情

**错误信息**:
```
('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
```

**发生频率**: 100% (所有股票)

**重试次数**: 3次/股票

**影响范围**: 
- 所有31个股票的数据抓取
- 只能通过 BaoStock 备选方案获取 data

---

## 根因分析

### 可能原因

1. **网络连接问题**
   - AKShare 的数据源服务器可能无法访问
   - 本地网络配置问题（代理、防火墙）

2. **AKShare版本问题**
   - 当前安装的 AKShare 版本可能过旧
   - API接口可能已变更

3. **数据源限制**
   - AKShare 可能对请求频率有限制
   - IP被临时封禁

4. **数据源失效**
   - AKShare 依赖的数据源可能已失效
   - 数据源API地址变更

---

## 修复方案（已实施）

### 实施内容

已实现多数据源冗余机制 (`scripts/data_source_manager.py`)：

1. **数据源优先级**  
   - 主数据源: **BaoStock**（稳定、免费）
   - 备用数据源1: **Tushare**（需要token）
   - 备用数据源2: **AKShare**（当前连接失败）

2. **自动切换机制**  
   - 主数据源失败时自动尝试备用数据源
   - 数据源健康检查（定期探测）
   - 数据源状态缓存（避免频繁探测）

3. **改进的文件**  
   - `data/fetch_data.py`: 使用 `DataSourceManager` 替代直接调用 AKShare
   - `scripts/data_source_manager.py`: 新增，实现多数据源冗余
   - `scripts/test_data_source_manager.py`: 单元测试

### 代码改动

**改动文件**:
- `data/fetch_data.py` (改进版，使用 DataSourceManager)
- `scripts/data_source_manager.py` (新增，147行)
- `scripts/test_data_source_manager.py` (新增，单元测试)

**改动行数**: ~200 行

**兼容性**: 
- 向后兼容（保留 `fetch_with_baostock()` 但标记为弃用）
- 不影响现有功能

---

## 验证步骤

### 1. 单元测试（不依赖外部API）

```bash
python scripts/test_data_source_manager.py
```

**期望结果**: 所有测试通过

### 2. 数据源健康检查

```bash
python -c "
from scripts.data_source_manager import DataSourceManager
m = DataSourceManager()
print(m.health_check())
"
```

**期望结果**: 显示各数据源健康状态

### 3. 实际数据获取测试

```bash
# 测试单只股票
python data/fetch_data.py 000001 20260610 20260616
```

**期望结果**: 成功从可用数据源获取数据

---

## 待完成事项

- [ ] 确认至少一个数据源可用（BaoStock/AKShare/Tushare）
- [ ] 如果 Tushare 需要，配置 `tushare_token`
- [ ] 监控数据源状态，失败时告警
- [ ] 添加数据源响应时间统计
- [ ] 集成到 `scripts/backfill_data.py`

---

## 附件

- `scripts/data_source_manager.py`: 数据源管理器
- `data/fetch_data.py`: 改进的数据获取脚本
- `scripts/test_data_source_manager.py`: 单元测试

---

**报告人**: 数据 Agent (data-agent)  
**修复人**: dev-agent  
**验收人**: QA Agent (qa-agent)  
**验收时间**: 2026-06-18 17:05  
**验收结果**: ✅ 通过  
**测试报告**: `pm/test_reports/TEST-2026-06-18-001.md`  

---

## 验收记录（2026-06-18）

### QA 验收结果
✅ **通过（Verified）**

**验收测试**:
1. ✅ 数据源健康检查：BaoStock 可用，Tushare 未安装，AKShare 连接失败（符合预期）
2. ✅ 实际数据获取：成功从 BaoStock 获取 5 行数据
3. ✅ 单元测试：所有测试通过（`test_data_source_manager.py`）
4. ✅ 集成测试：`data/fetch_data.py` 正常工作
5. ✅ 数据文件验证：列名标准化正确

**发现问题**:
- 🟡 `scripts/backfill_data.py` 未集成 `DataSourceManager`（低优先级，不影响功能）

**结论**: 多数据源冗余机制已实现并工作正常，BUG-20260616-001 验收通过。

---

**END OF BUG REPORT**
