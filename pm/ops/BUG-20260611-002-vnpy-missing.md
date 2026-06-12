# BUG-20260611-002: vnpy 未安装，QMT 交易网关无法加载

**创建时间：** 2026-06-11 19:06  
**严重等级：** S2  
**状态：** fixed  
**修复时间：** 2026-06-12  
**影响：** 无法使用 QMT 实盘交易功能（当前为 sim 模式，影响有限）

---

## 描述

`gateways/qmt_gateway.py` 和 `gateways/realtime_price_gateway.py` 依赖 `vnpy`，但 `.venv` 中未安装该包，导致导入失败：

```python
from gateways import qmt_gateway
# ImportError: No module named 'vnpy'
```

## 复现步骤

```python
from gateways import qmt_gateway  # 必现
```

## 建议修复

如需 QMT 功能：

```bash
cd C:\Users\Administrator\.openclaw\workspace\quant-learn
.venv\Scripts\pip.exe install vnpy vnpy-qmt
```

如不需要 QMT，在 `config.yaml` 中明确设置 `broker.mode: sim` 并注释/移除 QMT 相关导入。

## 修复记录（2026-06-12）

### 根因确认
`gateways/__init__.py` 直接 `from .qmt_gateway import QmtGateway`，当 `.venv` 中未安装 `vnpy` 时，任何 `import gateways` 都会失败。

### 修复方案
修改 `gateways/__init__.py`：
1. 将 `QmtGateway` 导入改为 `try/except ImportError`
2. `vnpy` 未安装时静默跳过，不影响 `RealtimePriceGateway` 等其他模块
3. 显式导入 `RealtimePriceGateway`（原本没有）

### 验证结果
```bash
python -c "
from gateways import RealtimePriceGateway
print('RealtimePriceGateway 导入成功')
try:
    from gateways import QmtGateway
    print('QmtGateway 可用（vnpy 已安装）')
except ImportError:
    print('QmtGateway 不可用（vnpy 未安装，预期行为）')
"
# 输出：
# RealtimePriceGateway 导入成功
# QmtGateway 不可用（vnpy 未安装，预期行为）
```

### 状态历史
| 时间 | 状态 | 说明 |
|------|------|------|
| 2026-06-11 19:06 | open | Bug 创建 |
| 2026-06-12 15:50 | fixed | gateways/__init__.py 可选导入已实现 |
