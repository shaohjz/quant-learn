# 策略参数自动采纳 — 2026-09-04

- 判定：**未采纳**
- 原因：auto_apply.enabled=false，自动写入已关闭
- PromotionGate：未通过
- 假设编号：（无）
- 备份：（首次采纳，无历史文件）

## 逐项判定

| 参数 | 当前 | 提案 | 实际写入 | 结果 | 说明 |
|------|-----:|-----:|--------:|:----:|------|
| `swing_strategy.execution.min_score_buy` | 5 | 7 | 6 | clamped | 变动超过单次上限 20%，夹到 6 |
| `swing_strategy.signals.a_ma20_tolerance` | 0.015 | 0.02 | 0.018 | clamped | 变动超过单次上限 20%，夹到 0.018 |
| `swing_strategy.signals.b_ma10_tolerance` | 0.01 | 0.015 | 0.012 | clamped | 变动超过单次上限 20%，夹到 0.012 |

## 回滚

```bat
.venv\Scripts\python.exe -u scripts\apply_strategy_params.py --rollback
```
