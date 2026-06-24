# BUG-20260624-003: daily_review.py generate_report() 中仍有大量 Unicode 表情未替换

## 基本信息
- **Bug ID**: BUG-20260624-003
- **标题**: `generate_report()` 中仍有大量 Unicode 表情未替换，GBK 终端可能触发 UnicodeEncodeError
- **状态**: deployed
- **优先级**: P2
- **创建时间**: 2026-06-24
- **创建人**: QA Agent (qa-agent)
- **指派给**: dev-agent
- **关联 Bug**: BUG-20260624-002（修复不完整，已 reopened）

## 描述
`BUG-20260624-002` 的修复只替换了 3 处 `print()` 语句中的 Unicode 表情符号，但 `generate_report()` 函数（生成企微推送 Markdown 内容）中仍有约 10+ 处 Unicode 表情未处理。

当 `print(report)` 在 Windows cmd.exe（GBK 代码页 936）中执行时，仍可能触发 `UnicodeEncodeError: 'gbk' codec can't encode character`。

## 未修复的 emoji 位置（`scripts/daily_review.py`）

| 行号 | 内容 | 建议替换 |
|------|------|-----------|
| 116 | `f"⚠️ 止损预警：..."` | `[警告] 止损预警：...` |
| 122 | `f"🎉 止盈提示：..."` | `[止盈] 止盈提示：...` |
| 128 | `f"🔴 移动止损触发：..."` | `[卖出] 移动止损触发：...` |
| 149 | `"## 📊 账户概况"` | `"## 账户概况"` |
| 155 | `"🟢"` / `"🔴"` / `"⚪"` | `"[买入]"` / `"[卖出]"` / `"[持仓]"` |
| 177 | `"## 🚨 风险预警"` | `"## 风险预警"` |
| 183 | `"## 📈 今日策略信号"` | `"## 今日策略信号"` |
| 195 | `"> ✅ 无止损/止盈触发预警"` | `"> 无止损/止盈触发预警"` |
| 201 | `"## ⚠️ 阈值状态异常"` | `"## 阈值状态异常"` |

> 注：以上行号基于当前 `daily_review.py` 版本，实际以代码为准。

## 影响
1. 在 Windows cmd.exe（GBK 代码页）运行 `python scripts/daily_review.py` 时，`print(report)` 可能触发 `UnicodeEncodeError`
2. 企微 Markdown 推送内容含 emoji，部分客户端可能显示异常
3. `BUG-20260624-002` 的修复不完整，Bug 已被 QA 打回 `reopened`

## 建议修复方案

### 方案 A（推荐）：全部替换为纯文本
将 `generate_report()` 中所有 emoji 统一替换为纯文本标记（与已修复的 3 处保持一致）：
- ⚠️ → `[警告]`
- 🎉 → `[止盈]`
- 🔴 → `[卖出]`
- 🟢 → `[买入]`
- ⚪ → `[持仓]`
- ✅ → `[成功]`
- 🚨 → `【风险】`
- 📊 → `【账户】`
- 📈 → `【策略】`

### 方案 B：统一 Unicode 安全处理
在 `daily_review.py` 顶部增加：
```python
import sys
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
```
> 不推荐：治标不治本，企微 Markdown 中的 emoji 仍可能在某些客户端异常显示。

## 验收标准
1. ✅ `generate_report()` 生成的 Markdown 内容不含任何 Unicode 表情符号（或已做兼容处理）
2. ✅ 在 Windows cmd.exe（GBK 代码页 936）中运行 `python scripts/daily_review.py` 无 `UnicodeEncodeError`
3. ✅ 企微推送内容可读，无乱码

## 状态历史
- 2026-06-24 17:10: 由 QA Agent 创建（BUG-20260624-002 验收不通过衍生）
- 2026-06-24 17:10: 状态 `open`，指派给 dev-agent
- 2026-06-24 18:05: 随 BUG-20260624-002 一起修复完成（替换所有 emoji 为纯文本标记），状态 `fixed`
- 2026-06-24 18:06: QA 验收通过，状态 `verified`（测试报告 TEST-2026-06-24-003.md）
- 2026-06-24 18:38: 部署到 production，状态 `deployed`

---
*END OF BUG REPORT*
