# REQ-034: 双账户执行一致性诊断与镜像差异归因

## 功能概述

自动诊断模拟盘（sim）与实盘（QMT live）之间的执行差异，并给出原因分类和处理建议。

## 诊断维度

1. **持仓差异**：sim 有持仓但 live 为空
2. **成交差异**：sim 有成交记录但 live 没有
3. **现金利用率差异**：sim 已全仓但 live 仍全现金
4. **订单状态异常**：被拒绝、超时、部分成交等

## 原因分类

| 原因代码 | 说明 | 处理建议 |
|---------|------|----------|
| `not_started` | 实盘未开启 / QMT 未登录 | 确认 QMT 已登录且策略已启动 |
| `risk_blocked` | 风控拦截（仓位超限、单笔超限） | 检查实盘风控设置 |
| `order_failed` | 下单失败（资金不足、系统拒绝） | 查看 QMT 日志确认原因 |
| `sync_delay` | 同步延迟（订单已发出但未成交） | 等待或手动刷新订单状态 |
| `config_mismatch` | 账户配置差异（初始资金不同） | 检查双账户配置一致性 |
| `broker_rejected` | 券商/交易所拒绝（涨跌停、停牌） | 检查价格是否合规 |
| `timeout` | 订单超时未成交 | 调整价格或重新下单 |
| `partial_fill` | 部分成交 | 检查剩余订单状态 |

## 文件结构

```
quant-learn/
├── sim/
│   └── mirror_diagnostics.py   # 核心诊断器
├── scripts/
│   ├── push_diagnostics.py      # 推送诊断报告到企微
│   └── push_diag_now.py        # 直接执行推送
└── output/
    └── diag/                    # 诊断报告输出目录
        ├── mirror_diag_YYYYMMDD.md
        └── mirror_diag_YYYYMMDD.json
```

## 使用方式

### 1. 命令行直接运行

```bash
# 诊断今天的差异，并打印报告
python sim/mirror_diagnostics.py --print

# 诊断指定日期，保存报告
python sim/mirror_diagnostics.py --date 2026-06-01

# 只打印不保存
python sim/mirror_diagnostics.py --date 2026-06-01 --print
```

### 2. 推送诊断报告到企微

```bash
# 推送摘要（默认）
python scripts/push_diagnostics.py

# 推送完整详细报告
python scripts/push_diagnostics.py --detail

# 只生成不推送（dry-run）
python scripts/push_diagnostics.py --dry-run
```

### 3. 集成到每日复盘

在 `scripts/daily_review.py` 中已集成诊断功能，每日自动复盘时会自动运行诊断并将摘要附加到企微推送消息中。

## 集成位置

1. **每日复盘自动集成**（`scripts/daily_review.py`）：
   - `generate_wecom_summary()` 函数已增加 `include_diagnostics` 参数
   - 默认开启，在企微摘要中自动附加诊断摘要

2. **独立诊断推送**（`scripts/push_diagnostics.py`）：
   - 可单独运行，推送完整诊断报告
   - 支持 `--detail` 参数推送完整报告

3. **核心诊断器**（`sim/mirror_diagnostics.py`）：
   - `MirrorDiagnostics` 类封装了所有诊断逻辑
   - 可被其他模块导入使用

## 输出格式

### Markdown 报告结构

```markdown
# 🔍 双账户一致性诊断报告
**诊断日期**: YYYY-MM-DD
**生成时间**: ...

## 📊 诊断概览
- 总差异数: N
- 严重: N | 警告: N | 提示: N
- 持仓差异: N 项
- 成交差异: N 项

## 🎯 原因分布
- 实盘未开启/未运行: N 项
- 风控拦截: N 项
...

## 🔎 详细问题
### 🔴 问题 1: position_mismatch
**股票**: 林洋能源 (601222)
**模拟盘**: 3000股 @¥6.39 市值¥19230
**实盘**: 空仓
**原因**: 实盘未开启/未运行
**建议**: 检查实盘 QMT 是否开启了自动交易
...

## 📝 诊断结论
发现 N 项差异...

## ✅ 行动建议
- 🔴 [紧急] 确认 QMT 已登录...
...
```

## 配置要求

1. **数据库**：需要 `sim_live_mirror.db` 包含双账户数据
2. **Webhook**：需要在 `config.yaml` 中配置 `notifier.wecom_webhook`
3. **账户 ID**：
   - 模拟盘：默认 ID=1
   - 实盘：默认 ID=2（可以通过参数覆盖）

## 技术实现

1. **数据查询**：直接从 SQLite 数据库查询 `sim_account`, `sim_positions`, `sim_trades`, `sim_orders` 表
2. **差异检测**：对比双账户在相同日期的数据
3. **原因推断**：
   - 检查 `sim_orders` 表的状态字段（REJECTED, CANCELLED 等）
   - 对比持仓和成交记录的存在性
   - 分析现金利用率差异
4. **报告生成**：结构化数据 → Markdown/JSON 渲染

## 测试验证

已通过测试：
- ✅ 成功检测到 17 项差异（14 项严重，2 项警告）
- ✅ 正确识别原因：实盘未开启（14 项）、配置差异（2 项）、风控拦截（1 项）
- ✅ 成功推送诊断摘要到企微

## 后续优化方向

1. **自动修复建议**：基于差异类型提供一键修复命令
2. **趋势分析**：追踪差异数量的变化趋势
3. **告警阈值**：当差异数超过阈值时自动告警
4. **可视化**：生成差异分布图表
