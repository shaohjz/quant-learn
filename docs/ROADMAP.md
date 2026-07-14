# 📊 量化学习项目路线图

> 项目路径：`C:\Users\Administrator\.openclaw\workspace\quant-learn`
> 模拟盘DB：`data/sim_live_mirror.db` | PM DB：`data/pm.db`
> 最后更新：2026-07-14

---

## 一、项目概况

一个基于 Python 的 A 股量化交易学习系统，集成了：
- **模拟盘交易引擎**（`sim/` 模块）
- **策略信号生成**（`strategies/`、`vqlearn/`）
- **量化核心库**（`quant_core/`）
- **数据获取**（akshare、腾讯行情、baostock 等多数据源）
- **通知推送**（企微 webhook）
- **研发管理**（pm.db 任务追踪）
- **短线波段扫描**（`scripts/swing_auto.py`）
- **定时任务**（OpenClaw cron，LLM agent 驱动）

---

## 二、已完成 ✅

### 核心引擎
- [x] `quant_core/` 量化核心库（domain、execution、fees、metrics、portfolio、risk、strategy）
- [x] `sim/` 模拟盘引擎（engine、portfolio、signal_generator、reporter、discipline 等）
- [x] `vqlearn/` 新一代量化框架（backtest、strategies、threshold_state、buy_risk_guard）
- [x] `broker/` 券商接入层（sim_broker、qmt_broker、trading_gate）
- [x] `gateways/` 数据网关（qmt_gateway、realtime_price_gateway）
- [x] `decision/fusion_engine.py` 融合决策引擎
- [x] `notifier/` 通知模块

### 策略与信号
- [x] 多策略信号生成（threshold_alert、buy_zone、buy_strong、trend_break）
- [x] `strategies/` 策略库（MACD、SMA交叉、布林带、融合策略、复合策略）
- [x] `scripts/swing_auto.py` 短线波段扫描（稳定型股票池、技术分析、盈亏比计算）
- [x] `scripts/swing_scan.py` / `swing_scanner.py` 早期波段扫描
- [x] `scripts/news_signal_fetcher.py` 新闻信号获取（akshare 拉取+写入DB）
- [x] `scripts/stop_loss_auto.py` / `stop_loss_auto_sell.py` 自动止损
- [x] `scripts/stop_profit_monitor.py` 止盈监控
- [x] `scripts/fusion_engine.py` 信号融合

### 数据层
- [x] 多数据源管理（akshare、baostock、腾讯行情、mootdx）
- [x] 数据质量检查（`scripts/check_data_freshness.py`、`data_integrity_check.py`）
- [x] K线数据获取与缓存
- [x] `skills/a-stock-data-signals/` 解禁预警、盘前检查、盘后信号日报

### 通知与报告
- [x] 企微 webhook 推送（`notifier/wecom_notifier.py`、`scripts/wecom_webhook.py`）
- [x] 每日复盘报告（`scripts/daily_review.py`、`gen_daily_report.py`）
- [x] 收盘日报（`scripts/daily_close_report.py`）
- [x] 盘中监控（`scripts/intraday_scanner.py`、`notify_intraday.py`）
- [x] 盘前简报（`scripts/morning_brief.py`、`morning_scanner.py`）
- [x] 观察池生成（`scripts/generate_next_watchlist.py`）
- [x] 月度/周度回顾（`scripts/monthly_review.py`、`weekly_review.py`）

### 研发管理
- [x] `pm.db` 任务追踪系统（`scripts/pm_cli.py`）
- [x] 每日研发闭环工作流（`pm/daily/`）
- [x] Bug 追踪（`pm/bugs/`）
- [x] 测试报告（`tests/` + `pm/test_reports/`）
- [x] 部署日志（`pm/deploy/`）
- [x] 运维日志（`pm/ops/`）

### 定时任务（OpenClaw Cron）
- [x] 9:00 研发验收（`研发验收-9点`）
- [x] 9:00 解禁预警（`a-stock-data 解禁预警`）
- [x] 9:05 盘前检查（`a-stock-data 盘前检查`）
- [x] 9:10 新闻信号分析（`新闻信号分析`）
- [x] 15:05 盘后信号日报（`a-stock-data 盘后信号日报`）
- [x] 15:05 收盘交易日报（`收盘交易日报`）
- [x] 16:00 短线波段扫描（`短线波段扫描-每日收盘`）
- [x] 18:00 研发修复（`研发修复-18点`）
- [x] 20:00 PM Agent 日报（`pm-agent-daily-report`）
- [x] 20:00 理财师复盘（`理财师-每日复盘汇报`）
- [x] 21:00 研发修复（`研发修复-21点`）

---

## 三、进行中 🔄

### P0 紧急
| ID | 标题 | 状态 | 说明 |
|----|------|:----:|------|
| REQ-048 | 止损执行链路 Bug | testing | threshold_state 已标记 executed 但 sim_positions 未卖出 |
| REQ-057 | 盘中14信号executed但0笔买入成交 | testing | 信号-执行链路断裂复发 |
| TASK-20260709-2004-001 | buy_zone 信号参考价/MA10 价系统性错乱 | testing | 002709/600021/001896 串价 |

### P1 待修复
| ID | 标题 | 状态 | 说明 |
|----|------|:----:|------|
| REQ-011 | 接入vnpy OmsEngine | pending | 详细订单成交回放 |
| REQ-043 | 去大模型化 | pending | agentTurn → systemEvent，降低LLM消耗 |
| REQ-058 | 持仓清仓后 threshold_state 悬挂记录未自动失效 | verified | 002709 案例 |
| REQ-060 | news_sentiment 影子信号 price=0 且 stock_name 未解析 | verified | 全样本系统性缺陷 |
| REQ-062 | buy_zone/buy_strong信号文本参考价仍串价 | verified | 展示未修复 |
| REQ-063 | sim_daily_nav连续缺失 | verified | 07-11/07-12/07-13 无记录 |

### P2 待开发
| ID | 标题 | 状态 | 说明 |
|----|------|:----:|------|
| REQ-019 | QMT订单/成交状态流 | pending | 实时同步展示 |
| REQ-005 | 观察列表K线缩略图 | testing | |
| REQ-015 | 自动获取用户手工填写的复盘要点 | testing | |
| REQ-020 | 双账户复盘支持交易异动提醒 | testing | 跌破阈值自动警示 |
| REQ-027 | 交易纪律打卡与知行合一评分 | testing | |
| REQ-030 | 自动统计策略信号触发的交易盈亏 | testing | |

---

## 四、待办（新需求）📋

### 波段交易相关
- [ ] **波段交易日报**：每天收盘后推送波段扫描结果+波段持仓盈亏
- [ ] **波段策略回测**：对 swing_auto.py 的选股逻辑做历史回测
- [ ] **波段信号分级推送**：A类（高盈亏比）自动推送，B/C类可选
- [ ] **波段持仓止损线**：在 swing_positions 表中增加止损价字段

### 模拟盘改进
- [ ] **测试数据隔离**：清理 sim_positions 中的测试股票（Test0/1/2）
- [ ] **同日买卖保护**：买入后冷却期内不触发卖出信号
- [ ] **非交易日自动识别**：复盘脚本自动使用最近交易日数据
- [ ] **多账户净值曲线**：主账户+波段账户分开展示

### 数据与监控
- [ ] **数据源健康监控**：定时检查所有数据源可用性，异常时告警
- [ ] **盘中实时信号推送**：14:00左右推送当日信号汇总
- [ ] **北向资金日报**：每日北向资金流向统计
- [ ] **行业轮动监控**：申万一级行业涨跌幅排名

### 研发管理
- [ ] **需求文档版本化**：ROADMAP.md 纳入 git 管理
- [ ] **自动化测试覆盖率**：核心模块单元测试覆盖
- [ ] **发布流程规范化**：测试→验收→部署 三阶段门禁

### 定时任务（待添加）
- [ ] **波段扫描结果推送**：swing_auto.py 执行后自动推送到企微
- [ ] **盘中信号汇总推送**：14:00 推送当日信号汇总
- [ ] **数据源健康检查**：每日开盘前检查数据源状态

---

## 五、已关闭/不再维护 ❌

- REQ-002: 完整采样（已完成）
- REQ-003: K线数据质量（已完成）
- REQ-004: 每日扫描通知（已完成）
- REQ-005: 总资产显示修复（已完成）
- REQ-034: 执行一致性（已完成）
- REQ-044: 设置文档（已完成）
- REQ-065: 累计收益率修复（已完成）
- REQ-066: 重置后自动交易（已完成）
- REQ-059: buy_zone 串价 bug（已修复，待验证）
- REQ-061: 龙旗科技移动止损未执行（已修复，待验证）

---

## 六、技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| 数据获取 | akshare、baostock、腾讯行情API、mootdx |
| 数据库 | SQLite（`sim_live_mirror.db` + `pm.db`） |
| 通知 | 企微 webhook |
| 定时任务 | OpenClaw Cron（LLM agent 驱动） |
| 策略引擎 | 自研 `quant_core` + `vqlearn` |
| 回测 | `vqlearn/runners/` + `research/walk_forward.py` |

---

## 七、项目结构

```
quant-learn/
├── sim/                    # 模拟盘核心引擎
├── quant_core/             # 量化核心库
├── vqlearn/                # 新一代量化框架
├── strategies/             # 策略库
├── broker/                 # 券商接入
├── gateways/               # 数据网关
├── decision/               # 决策引擎
├── notifier/               # 通知模块
├── scripts/                # 脚本（交易、扫描、报告、工具）
├── skills/                 # OpenClaw 技能
├── tests/                  # 测试
├── data/                   # 数据文件
├── output/                 # 输出报告
├── pm/                     # 研发管理
├── docs/                   # 文档
├── config.yaml             # 主配置
└── docs/ROADMAP.md         # 本文件
```
