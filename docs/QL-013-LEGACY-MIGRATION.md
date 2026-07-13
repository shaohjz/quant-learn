# QL-013: 旧链路下线计划

> 状态: 标记弃用中（等 QL-014 稳定运行后再删除）
> 日期: 2026-07-13

## 需要弃用的旧入口和重复实现

### 多版本脚本
| 旧路径 | 替代 | 状态 |
|--------|------|------|
| `run_daily.py` | `run_daily_improved.py` → 统一到 sim/engine | 🟡 标记弃用 |
| `sim_executor.py` | `sim_executor_v2.py` → 统一到 sim/engine | 🟡 标记弃用 |

### 多套配置
| 旧路径 | 替代 | 状态 |
|--------|------|------|
| `config/config.yaml` | 根 `config.yaml` | 🟡 弃用告警已加 (QL-004) |
| `vqlearn/config/portfolio.yaml` | 根 `config.yaml` watchlist | 🟡 弃用告警已加 (QL-004) |

### 多套 Webhook/通知
| 旧路径 | 替代 | 状态 |
|--------|------|------|
| `wecom_webhook.py` (根目录) | `notifier/wecom_notifier.py` | 🟡 标记弃用 |
| `scripts/wecom_webhook.py` | `notifier/wecom_notifier.py` | 🟡 标记弃用 |

### 根目录散落的测试/临时文件
| 旧路径 | 状态 |
|--------|------|
| `test_auto_trade_flow.py` | 🟡 标记弃用 (pytest不收集) |
| `test_auto_trade_flow_v2.py` | 🟡 标记弃用 |
| `test_auto_trade_real.py` | 🟡 标记弃用 |
| `test_auto_trader.py` | 🟡 标记弃用 |
| `test_data_source.py` | 🟡 标记弃用 |
| `check_*.py` 系列 | 🟡 标记弃用 |
| `*_fixed.py` / `*_temp.py` | 🔴 候选删除 |

### 硬编码 RULES/HOLDINGS
| 位置 | 替代 | 状态 |
|------|------|------|
| 根目录脚本中的硬编码阈值 | `config.yaml` watchlist | 🟡 标记弃用 |

## 操作步骤

1. ✅ 给旧配置文件加弃用告警 (QL-004 config_resolver.py)
2. ✅ pytest 只收集 tests/ 目录 (QL-002 pyproject.toml)
3. 🟡 给旧脚本入口加 `warnings.warn(DeprecationWarning)`
4. ⏳ 确认 Windows Task Scheduler / cron / 文档不再调用旧入口
5. ⏳ 将仍需保留的脚本移到 `legacy/`
6. ⏳ 最终删除（QL-014 稳定运行后）

## 回滚方案

每个删除操作单独提交，可 `git revert` 逐个恢复。
