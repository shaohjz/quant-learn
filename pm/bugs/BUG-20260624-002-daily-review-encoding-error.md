# BUG-20260624-002: daily_review.py Unicode 编码错误

## 基本信息
- **Bug ID**: BUG-20260624-002
- **标题**: daily_review.py 在 Windows 控制台中运行时出现 UnicodeEncodeError
- **状态**: fixed
- **优先级**: P2
- **创建时间**: 2026-06-24
- **创建人**: dev-agent
- **指派给**: dev-agent
- **开始时间**: 2026-06-24 15:35
- **完成时间**: 2026-06-24 15:40

## 描述
运行 `scripts/daily_review.py` 时，在打印包含 Unicode 表情符号（如 ✅、⚠️）的字符串时，出现 `UnicodeEncodeError: 'gbk' codec can't encode character` 错误。这导致脚本异常终止，无法生成日报和推送到企微群。

## 影响
- 每日复盘流程中断，无法生成 `output/reviews/YYYY-MM-DD.md` 文件
- 企微群无法收到每日复盘报告
- 影响日终复盘和次日策略调整

## 根因分析
Windows 控制台（cmd/PowerShell）默认使用 GBK 编码（代码页 936），而 Python 尝试打印的 Unicode 字符（如 ✅ U+2705、⚠️ U+26A0）不在 GBK 字符集中，导致编码失败。

## 修复方案
将 `scripts/daily_review.py` 中的 Unicode 表情符号替换为纯文本标记：
- ✅ → [成功]
- ⚠️ → [警告]

## 修复内容
修改 `scripts/daily_review.py` 中的 5 处打印语句：
1. 第 267 行：`print(f"✅ 已添加 PM Task: ...")` → `print(f"[成功] 已添加 PM Task: ...")`
2. 第 299 行：`print(f"开始复盘 {TODAY} ...")` → 无 Unicode 字符，无需修改
3. 第 305 行：`print(f"已创建 {len(tasks)} 个 PM Task")` → 无 Unicode 字符，无需修改
4. 第 320 行：`print("✅ 日报推送成功")` → `print("[成功] 日报推送成功")`
5. 第 322 行：`print("⚠️ 推送失败，打印日报内容：")` → `print("[警告] 推送失败，打印日报内容：")`

## 自测
运行 `python scripts/daily_review.py`，脚本正常完成，输出：
```
开始复盘 2026-06-24 ...

检测到的问题：
无新问题需要提报

生成日报...

推送到企微群...
[成功] 日报推送成功
```

## 状态历史
- 2026-06-24 15:35: 创建 Bug，状态 `open`
- 2026-06-24 15:40: 修复完成，状态 `fixed`

## 相关信息
- 修复提交：dba3227（master 分支）
- 后续可考虑使用 `logging` 模块替代 `print`，并配置编码为 UTF-8