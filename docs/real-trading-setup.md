# 实盘跟单配置指引

> 文档版本：v1.0 | 更新时间：2026-06-10 | 关联 BUG-005

## 背景

QuantLearn 支持**双账户模式**：
- **学习账户**（`account_id=1`，DB 名 `live_mirror`）：策略模拟盘，自动执行买卖信号
- **真实账户**（`account_id=2`，DB 名 `real_portfolio`）：真实 QMT 账户持仓镜像，默认不自动交易

当 `broker.mode=sim` 时，策略只在学习账户模拟成交，真实账户不会自动下单——这是**预期行为**，不是 Bug。

---

## 双账户执行逻辑说明

| broker.mode | accounts.learn.auto_trade | accounts.real.auto_trade | 学习账户 | 真实账户 |
|---|---|---|---|---|
| `sim` | true | false（默认） | ✅ 自动交易 | ❌ 仅镜像，不自动交易 |
| `qmt` | true | true | ✅ 自动交易 | ✅ 自动跟单 |
| `qmt` | true | false | ✅ 自动交易 | ❌ 仅记录信号，不下单 |

> **关键**：真实账户自动跟单需要 **同时满足** `broker.mode=qmt` **且** `accounts.real.auto_trade=true`。

---

## 开启真实账户自动跟单（Step by Step）

### 前置条件

1. **QMT 客户端已安装并登录**，且订阅了交易回调
2. **`gateways/qmt_config.json` 配置正确**（账号、端口等）
3. 建议先在小资金/模拟盘中验证，确认信号正确再开启实盘

### Step 1：修改 `config.yaml`

```yaml
broker:
  mode: qmt          # ← 从 sim 改为 qmt

accounts:
  real:
    auto_trade: true  # ← 从 false 改为 true
    # max_position_value: 50000  # 可选：单票上限，建议设置
    # max_total_value: 200000    # 可选：总仓位上限
```

### Step 2：验证 QMT 连接

```bash
python scripts/test_qmt_connect.py
```

预期输出：
```
✅ QMT 连接成功
✅ 账号：8888xxxxxxxx
✅ 持仓：3 只
```

### Step 3：Dry Run 验证（强烈建议）

先不开真实下单，只记录信号：

```yaml
# config.yaml
accounts:
  real:
    auto_trade: false   # 保持 false，只记录信号

# 手动触发一次复盘，查看信号日志
python scripts/daily_review.py 2026-06-10
```

检查 `output/vqlearn_live.log`，确认信号符合预期后再开启 `auto_trade: true`。

### Step 4：开启自动跟单

```yaml
accounts:
  real:
    auto_trade: true
```

重启相关服务 / 重新运行 `portfolio_alert.py`，使配置生效。

### Step 5：监控实盘执行

- 查看 `output/vqlearn_live.log` 确认订单下达
- 在 QMT 客户端 → 交易 → 委托记录，确认订单状态
- 每日复盘报告查看"双账户执行一致性诊断"章节

---

## 风控建议

开启真实账户自动跟单前，请确认以下风控配置：

```yaml
risk:
  max_position_pct: 0.2        # 单票不超过总资金 20%
  max_total_positions: 6          # 最大持仓数
  stop_loss_pct: -0.08           # 止损线 -8%
  take_profit_pct: 0.15          # 止盈线 +15%
  max_daily_trades: 10            # 每日最多交易笔数
  max_daily_build_amount_pct: 0.3 # 每日最多建仓占总资金 30%
```

---

## 双账户不一致的常见原因

复盘报告中"双账户执行一致性诊断"章节会列出差异原因，以下是常见情况：

| 现象 | 原因 | 处理建议 |
|---|---|---|
| 学习账户有交易，真实账户无交易 | `broker.mode=sim` 或 `real.auto_trade=false` | 参考本文档开启跟单 |
| 学习账户有交易，真实账户也有交易但标的不同 | 两账户 `stock_pool` / 资金规模 / 风控参数不同 | 对齐两账户配置 |
| 学习账户有交易，真实账户 0 成交但 `auto_trade=true` | QMT 下单被拒（资金不足/风控拦截/停牌） | 查看 QMT 废单记录 |
| 持仓数量不同 | 真实账户有历史遗留持仓未同步 | 运行 `python scripts/sync_real_position.py` 同步 |

---

## 相关文件

- `config.yaml` — 主配置文件
- `gateways/qmt_gateway.py` — QMT 交易网关
- `gateways/qmt_config.json` — QMT 连接配置
- `scripts/daily_review.py` — 双账户一致性诊断（`render_execution_consistency_section()`）
- `scripts/sync_real_position.py` — 真实持仓同步脚本
- `output/vqlearn_live.log` — 实盘执行日志

---

## 常见问题 FAQ

**Q：开启 `auto_trade: true` 后，真实账户会立即下单吗？**
A：不会立即下单。策略信号在下一个交易时段触发时才会下单，建议先 Dry Run 验证。

**Q：如何紧急停止真实账户自动交易？**
A：将 `config.yaml` 中 `accounts.real.auto_trade` 改回 `false`，重启服务即可。

**Q：学习账户和真实账户可以用不同策略吗？**
A：当前共用同一套 `watchlist` 和策略参数。如需独立策略，需要扩展 `accounts.real` 配置段。

**Q：如何验证双账户一致性诊断是否正常？**
A：运行 `python scripts/daily_review.py 2026-06-10`，查看输出中的"🧭 双账户执行一致性诊断"章节。
