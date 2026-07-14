# legacy/ — 弃用文件

> 这些文件已被 `quant_core/` + `scripts/quant_engine.py` 替代。
> 保留仅供参考/回滚，**不要在新代码中 import 这些文件**。
> 计划在 QL-014 稳定运行后删除。

## 目录

| 路径 | 说明 |
|------|------|
| `root_junk/` | 根目录扫任务/临时脚本/杂 txt（2026-07-14 迁入） |
| `nested_windows_path_artifact/` | 误提交的 `C:\Users\...` 嵌套目录 |
| `run_daily.py(.backup)` / `wecom_webhook.py` / `test_auto_trade_*` | 旧入口 |

## 迁移映射

| 旧文件 | 新替代 |
|--------|--------|
| `run_daily.py` | `scripts/quant_engine.py` |
| `wecom_webhook.py` | `notifier/wecom_notifier.py` |
| `test_auto_trade_*.py` | `tests/test_quant_core.py` |
| `check_*.py` / `scan_tasks*` | `scripts/ops_*` / pm_cli |
| `*_fixed.py` / `*_temp.py` | 已清理，无需替代 |
