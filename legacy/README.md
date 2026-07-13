# legacy/ — 弃用文件

> 这些文件已被 `quant_core/` + `scripts/quant_engine.py` 替代。
> 保留仅供参考/回滚，**不要在新代码中 import 这些文件**。
> 计划在 QL-014 稳定运行后删除。

## 迁移映射

| 旧文件 | 新替代 |
|--------|--------|
| `run_daily.py` | `scripts/quant_engine.py` |
| `wecom_webhook.py` | `notifier/wecom_notifier.py` |
| `test_auto_trade_*.py` | `tests/test_quant_core.py` |
| `check_*.py` | `scripts/ops_check.py` (待建) |
| `*_fixed.py` / `*_temp.py` | 已清理，无需替代 |
