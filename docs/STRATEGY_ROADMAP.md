# 量化策略优化作战图（2026-05-22 起）

> 用户要求：全做。但我（assistant）建议**分批做，按 ROI 排序**，每完成一项就停下复盘。
> 单 session 推过去会引入新 bug，质量不可控。

## 📊 现状盘点（2026-05-21 23:00）

### 已有
- ✅ `scripts/sim_executor.py` - 模拟下单（含涨跌停拦截、伪实时价检测）
- ✅ `vqlearn/strategies/threshold_strategy.py` - 实盘策略（buy_zone/buy_strong/trend_break/take_profit）
- ✅ `vqlearn/runners/run_paper_with_strategy.py` - vnpy 实盘 runner
- ✅ `vqlearn/runners/run_backtest.py` - **简易回测**（只能统计触发次数，**不能算 PnL**）
- ✅ `backtest.py` + `scripts/batch_backtest_10k.py` - 老 backtrader 回测（只跑过 4 只股票，5 个老策略）
- ✅ `notifier/wecom_notifier.py` - 企微通知
- ✅ `vqlearn/services/signal_review.py` - 事后跟踪
- ✅ `daily_review.py` - 日复盘

### 未有 / 不靠谱
- ❌ **ThresholdAlertStrategy 从未真正回测** —— `run_backtest.py` 只能数触发次数，不能算 PnL/胜率/回撤
- ❌ **22 只股票的阈值是人工拍脑袋**（portfolio.yaml），无历史最优化
- ❌ **没有滑点 / 流动性 / 大盘环境过滤**
- ❌ **样本太少**（22 只），观察池静态，没有动态选股
- ❌ **策略和 IO 强耦合**（`_check_rules` 里调通知、写数据库、做交易时段判断）
- ❌ **没有开源方案对照**（不知道行业标杆是什么）

---

## 🎯 阶段 1：把"回测"从根上搭起来（这周）

### A. 调研开源方案，选一个抄作业 ⭐⭐⭐⭐⭐
**目标**：避免重新发明轮子，借鉴成熟框架的回测引擎设计。
- **vnpy_ctastrategy 自带回测**：类型 EngineType.BACKTESTING，能跑日 K/分钟 K，输出 PnL/胜率/回撤
- **backtrader**：老项目用过，文档好，社区大，分析器多
- **qstrader**（事件驱动，Quantopian 系）
- **bt**（pandas 基础，简洁）
- **VeighNa Studio**（vnpy 配套，有 GUI）
- **Quantitative Trading**（Github 开源量化框架，基础但齐全）

**选型方向**：
- **回测引擎用 backtrader 或 vnpy 的现成的**（不要自己写）
- **策略层独立**（写成纯函数 `decide(bars, position) -> action`），实盘和回测复用同一个策略层

### B. 把 ThresholdAlertStrategy 解耦成"纯策略 + IO 适配层" ⭐⭐⭐⭐⭐
- 抽出 `decide_signal(bars, holdings, rules) -> Signal`
- 实盘适配：vqlearn live tick → 调 decide → 收到 Signal → IO（通知 + sim_executor）
- 回测适配：历史 bar → 喂 decide → 收到 Signal → 模拟撮合 → 累计 PnL

### C. 用 vnpy 自带回测引擎跑 ThresholdAlertStrategy ⭐⭐⭐⭐⭐
- 先解决 5/19 那次 0 trades 的 bug
- 跑 22 只股票 × 2 年历史 = 44 个回测（约 5-10 分钟）
- 输出每只股票的：总收益 / 年化 / 胜率 / 回撤 / 夏普 / 交易数
- 写入 `output/vqlearn_backtest_summary.csv`

### D. 加滑点 + 手续费模型 ⭐⭐⭐⭐
- 买价 +0.3%，卖价 -0.3%（滑点）
- 佣金万 2.5（已有）+ 印花税 0.05%（已有）
- 跑出**带滑点的真实回测结果**，对比 #C 看缩水了多少

## 🎯 阶段 2：策略改进（下周）

### E. 大盘过滤 ⭐⭐⭐⭐
- 上证指数 / 沪深 300 在 ma20 之下时，不开新仓（只允许卖出）
- 挑战：vqlearn live 还没拉指数 tick

### F. 动态选股池 ⭐⭐⭐
- 现在 22 只是 portfolio.yaml 锁死的
- 改成每天/每周扫描全市场（约 5000 只）找符合"超跌 + 缩量止跌"的标的
- 进观察池前再做基本面过滤（流通市值、行业、PE）

### G. 阈值优化（grid search）⭐⭐⭐
- 用 #C 的回测结果做参数扫描：buy_zone 在 5%/7%/10%/15% 的回调位上分别测
- 找历史上各只股票最优阈值（注意过拟合！）

## 🎯 阶段 3：高级优化（下下周以后）

### H. 多策略并联 + 投票机制 ⭐⭐
- ThresholdAlert（区间反转）+ MACD（趋势跟随）+ 布林带（异常突破）三策略
- 多数票决定下单方向

### I. 风控模块 ⭐⭐⭐
- 单日最大亏损 / 单股最大持仓占比 / 行业集中度 / 强制止损线
- 触发风控时降仓位甚至清仓

### J. 实盘 1 个月真实战绩对照回测 ⭐⭐⭐⭐⭐
- 每天积累 vqlearn live 的真实信号 + 真实成交价
- 1 个月后看：实盘胜率 vs 回测胜率，差距多大？
- 如果差很多 → 回测高估；如果一致 → 系统稳健

---

## 📌 今晚（2026-05-22 凌晨）做哪几项？

**只挑高 ROI + 低风险的 1-2 项**：

1. **A 调研开源**（30 分钟，搜索/对比，输出报告）
2. **C 跑通 vnpy 回测**（修 0 trades bug，先把"有结果"跑出来）

**剩下的明天起按计划推进。**
