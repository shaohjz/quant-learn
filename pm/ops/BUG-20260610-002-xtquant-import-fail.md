# Bug 报告 — xtquant 模块导入失败

## Bug 信息
- **Bug ID**: BUG-20260610-002
- **创建时间**: 2026-06-10 19:05
- **严重级别**: S2（功能缺失）
- **状态**: ❌ 未修复（2026-06-12 巡检确认依然失败）
- **影响组件**: QMT 网关模块（交易 API）
- **连续天数**: 第3天

## 问题描述
xtquant 模块导入失败，导致 QMT 网关无法正常连接，交易 API 功能不可用。

## 复现步骤
1. 运行 `python check_qmt_status.py`
2. 观察错误信息：`No module named 'xtquant.IPythonApiClient'`
3. 尝试连接 QMT 网关时失败

## 预期行为
- xtquant 模块应正常导入
- QMT 网关应能正常连接
- 交易 API 功能应可用

## 实际行为
- xtquant 模块导入失败
- QMT 网关无法连接
- 交易 API 功能不可用

## 环境信息
- **操作系统**: Windows 10 10.0.26200
- **Python 版本**: 3.11+
- **QMT 路径**: D:\国金QMT交易端模拟\userdata_mini
- **xtquant 路径**: D:\国金QMT交易端模拟\bin.x64\Lib\site-packages

## 诊断结果
- ✅ QMT 网关配置正常
- ✅ QMT 路径配置正确  
- ✅ QMT 账户配置正确
- ❌ xtquant 模块导入失败
- ❌ 无法自动修复

## 解决方案

### 根本原因
Python 版本不兼容：
- 当前系统: Python 3.14.3
- QMT xtquant 要求: Python 3.10 或 3.11
- xtquant 的 .pyd 文件是针对 Python 3.10/3.11 编译的

### 修复步骤
1. **安装 Python 3.11**
   - 下载: https://www.python.org/downloads/release/python-3110/
   - 安装时勾选 "Add Python to PATH"

2. **创建虚拟环境**
   ```bash
   python3.11 -m venv venv_qmt
   venv_qmt\Scripts\activate
   pip install -r requirements.txt
   ```

3. **验证 xtquant 导入**
   ```bash
   python -c "from xtquant import xtdata; print('Success')"
   ```

### 临时 Workaround
如果无法立即安装 Python 3.11，禁用 QMT 网关功能：
```python
# 在 gateways/qmt_gateway.py 添加
import sys
if sys.version_info >= (3, 12):
    logger.warning("QMT xtquant 需要 Python 3.11 或更低版本")
    QMT_AVAILABLE = False
else:
    QMT_AVAILABLE = True
```

## 验证结果

### 安装 Python 3.11 后
- [ ] xtquant 模块成功导入
- [ ] QMT 网关正常连接
- [ ] 交易 API 功能可用

### 当前状态（2026-06-12 更新）
- ❌ Python 3.14 不兼容 xtquant（`.venv` 运行在 3.14）
- ❌ `vnpy` 未安装（`.venv` 中不存在）
- ⚠️ 当前 `broker.mode: sim`，不影响模拟交易
- ⚠️ 如需启用 QMT 实盘，必须先安装 Python 3.11 并创建独立 venv

## 后续行动
1. **如下周需实盘**: 安装 Python 3.11，创建 `venv_qmt`
2. **如不需实盘**: 在代码中明确禁用 QMT 导入，避免报错
3. **长期**: 考虑容器化或固定 Python 3.11 环境

---
**更新时间**: 2026-06-12 19:05
**更新人**: ops-agent-daily