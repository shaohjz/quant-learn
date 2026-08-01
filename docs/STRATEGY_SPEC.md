# 当前交易策略说明书

> 本文由 `scripts/strategy_review.py --write-spec` 从**代码和配置里抽取**生成，不要手改。
> 想改策略请改下表「取自」列指向的位置，重跑复盘后本文会自动跟上。

## #3 波段仓（account_id=3） `spec_hash=7e0813ecbd7b`

**沪深300+中证500 里挑稳定池 → 缩量回踩 MA10/MA20 买入 → 固定 5% 止损 / 8% 止盈**

### 选股范围

| 参数 | 当前值 | 取自 | 说明 |
|------|-------|------|------|
| 池子上限 | **50只** | `scripts/swing_pool_builder.py:DEFAULT_MAX_POOL` |  |
| 入池稳定分下限 | **70** | `scripts/swing_pool_builder.py:DEFAULT_MIN_SCORE` |  |
| 最小成交额 | **1 亿** | `scripts/swing_pool_builder.py:MIN_AMOUNT` |  |
| 股价下限 | **5元** | `scripts/swing_pool_builder.py:MIN_PRICE` |  |
| 股价上限 | **200元** | `scripts/swing_pool_builder.py:MAX_PRICE` |  |
| ATR 下限 | **1.5** | `scripts/swing_pool_builder.py:ATR_MIN` |  |
| ATR 上限 | **5.5** | `scripts/swing_pool_builder.py:ATR_MAX` |  |
| 日均振幅上限 | **6** | `scripts/swing_pool_builder.py:MAX_AVG_AMP` |  |
| 5 日跌幅下限 | **-8** | `scripts/swing_pool_builder.py:MAX_DROP_5D` |  |

### 买入条件

| 参数 | 当前值 | 取自 | 说明 |
|------|-------|------|------|
| 可成交信号类型 | **A/B** | `swing_params:execution.executable_types`<br>`scripts/swing_daily_report.py:EXECUTABLE_TYPES`<br>`scripts/swing_intraday_watch.py:EXECUTABLE` | A=缩量回踩MA20 B=缩量回踩MA10；C/D/E/F 只观察 |
| 信号分下限 | **5** | `swing_params:execution.min_score_buy`<br>`scripts/swing_daily_report.py:MIN_SCORE_BUY`<br>`scripts/swing_intraday_watch.py:DEFAULT_MIN_SCORE` |  |
| 净盈亏比下限 | **1.2** | `swing_params:filters.min_net_rr`<br>`scripts/swing_auto.py:MIN_NET_RR` |  |
| 预期涨幅下限 | **0.5%** | `swing_params:filters.min_upside_pct`<br>`scripts/swing_auto.py:MIN_UPSIDE` |  |
| 个股活性下限 | **1** | `swing_params:filters.min_avg_amp`<br>`scripts/swing_auto.py:MIN_AVG_AMP` | 日均振幅，太死的票不做 |

### 卖出条件

| 参数 | 当前值 | 取自 | 说明 |
|------|-------|------|------|
| 止损 | **5%** | `swing_params:execution.stop_loss_pct`<br>`scripts/swing_daily_report.py:STOP_LOSS_PCT`<br>`scripts/swing_intraday_watch.py:STOP_LOSS_PCT` |  |
| 止盈 | **8%** | `swing_params:execution.take_profit_pct`<br>`scripts/swing_daily_report.py:TAKE_PROFIT_PCT`<br>`scripts/swing_intraday_watch.py:TAKE_PROFIT_PCT` |  |

### 仓位与资金

| 参数 | 当前值 | 取自 | 说明 |
|------|-------|------|------|
| 最大持仓数 | **5只** | `swing_params:execution.max_positions`<br>`scripts/swing_daily_report.py:MAX_POSITIONS` |  |
| 单笔预算 | **1 万** | `swing_params:execution.single_budget`<br>`scripts/swing_daily_report.py:SINGLE_BUDGET` |  |
| 起始资金 | **5 万** | `config.yaml:accounts.swing.initial_cash` |  |
| 自动成交 | **关** | `config.yaml:accounts.swing.auto_trade` | false=只给挂单建议 |

### 交易成本

| 参数 | 当前值 | 取自 | 说明 |
|------|-------|------|------|
| 佣金率 | **0.00025** | `config.yaml:fees.commission_rate` |  |
| 印花税率 | **0.0005** | `config.yaml:fees.stamp_tax_rate` |  |

## #1 学习仓（account_id=1） `spec_hash=846eada0f2e4`

**手工观察池按 MA10 买区试探建仓 → config 风控闸门 + 半仓止盈 / -8% 硬止损**

### 选股范围

| 参数 | 当前值 | 取自 | 说明 |
|------|-------|------|------|
| 观察池规模 | **34只** | `config.yaml:watchlist.user_manual` | 盘前 daily_recalibrate 重算每只的 buy_zone/trend_break |

### 买入条件

| 参数 | 当前值 | 取自 | 说明 |
|------|-------|------|------|
| 强买通道 | **关** | `config.yaml:risk.buy_strong_enabled` | 关闭时只走 buy_zone |
| 每日新开仓上限 | **1笔** | `config.yaml:risk.max_daily_new_positions` |  |
| 浮亏禁加仓线 | **-3%** | `config.yaml:risk.block_add_to_loser_pct` |  |
| 大盘弱势禁买线 | **-1%** | `config.yaml:risk.market_panic_index_drop_pct` |  |

### 卖出条件

| 参数 | 当前值 | 取自 | 说明 |
|------|-------|------|------|
| 硬止损 | **-8%** | `config.yaml:risk.stop_loss_pct` |  |
| 止盈线 | **15%** | `config.yaml:risk.take_profit_pct` |  |
| 止盈方式 | **half** | `config.yaml:risk.take_profit_mode` | half=首次止盈卖一半 |
| 跟踪止损 | **atr_hybrid** | `config.yaml:risk.trailing.mode` |  |
| 跟踪启动浮盈 | **5%** | `config.yaml:risk.trailing.activate_profit_pct` |  |

### 仓位与资金

| 参数 | 当前值 | 取自 | 说明 |
|------|-------|------|------|
| 单笔预算 | **1 万** | `scripts/sim_executor.py:DEFAULT_BUY_BUDGET` |  |
| 最大持仓数 | **8只** | `config.yaml:risk.max_total_positions` |  |
| 单票市值上限 | **15%** | `config.yaml:risk.max_position_pct` |  |
| 起始资金 | **10 万** | `config.yaml:accounts.learn.initial_cash` |  |
| 自动成交 | **开** | `config.yaml:accounts.learn.auto_trade` |  |

### 风控闸门

| 参数 | 当前值 | 取自 | 说明 |
|------|-------|------|------|
| 单行业上限 | **30%** | `config.yaml:risk.max_industry_pct` |  |
| 单日成交上限 | **10笔** | `config.yaml:risk.max_daily_trades` |  |

### 交易成本

| 参数 | 当前值 | 取自 | 说明 |
|------|-------|------|------|
| 佣金率 | **0.00025** | `config.yaml:fees.commission_rate` |  |
| 印花税率 | **0.0005** | `config.yaml:fees.stamp_tax_rate` |  |
