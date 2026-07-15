# 量化学习项目路线图

> 项目路径：`C:\Users\Administrator\.openclaw\workspace\quant-learn`
> 模拟盘DB：`data/sim_live_mirror.db` | PM DB：`data/pm.db`
> 最后更新：2026-07-14（审计修订）

---

## 〇、审计结论（2026-07-14）

**总判：能跑模拟盘，但不宜当“已稳生产”。钱相关链路仍有洞。**

### 立刻危险（先修这些）
1. **止损只改状态、不减仓** — REQ-048 / REQ-061：代码侧已补 `record_sell_executed` 行数校验 / `reset_stuck_confirmed` / `audit_executed_without_trade`（2026-07-14）。产机需跑 `stop_loss_watch_runner.bat` + 验收。
2. **信号标 executed、零成交** — REQ-057：`_exec_via_sim` 已按 `trade is not None` 判成交；相关单测绿。
3. **串价** — REQ-062：`signal_reason` 改写为 `建仓价=成交价|触发阈值=...`，不再塞脏文案数字。TASK 串价等产机回归 002709 等。
4. **双调度打架** — OpenClaw cron + Windows `schtasks` 并存。见 `docs/CRON_JOBS.md`。
5. **LLM 改仓高风险** — 交易路径应收 `systemEvent`/bat（REQ-043 未做）。

### 2026-07-14 本轮已落地
- `vqlearn/services/threshold_state.py`：卖出闭环审计工具
- `scripts/sim_executor.py`：DB 缺表不挡卖、review_decisions 兼容、signal_reason 防串价
- `vqlearn/strategies/threshold_strategy.py`：下单带回 `trigger`
- `tests/test_req062_signal_reason_no_stale_price.py` + 既有 REQ-048/057/BUG-009 单测绿
- `scripts/stop_loss_watch_runner.bat`：盘中止损直跑
- 根目录 junk → `legacy/root_junk/`；旧报告 → `docs/archive/`；假 Windows 嵌套目录搬走

**产机还要你做**：`openclaw cron list` + `schtasks` 对账；挂上止损 bat；跑全量 pytest；QA 把 pm.db 标 verified。


### 仓库乱（非立即爆，但一直拖后腿）
| 问题 | 证据 |
|------|------|
| 多代框架并存 | `backtest.py` / `sim/` / `vqlearn/` / `quant_core/` / vnpy `runners/` |
| `scripts/` 坟场 | ≈350 个文件，大量 `_tmp_*` `_patch_*` `_check_*` |
| 根目录垃圾 | `=`、`run_daily.py.backup`、一堆 `test_*.py`、`PM_PROGRESS_*.md` |
| 错误嵌套路径 | 仓库内出现目录名 `C:\Users\Administrator\.openclaw\workspace\quant-learn` |
| 配置多套 | 根 `config.yaml` + `config/config.yaml` + `vqlearn/config/`（见 QL-013） |
| webhook 占位 | `config.yaml` 仍是 `YOUR_KEY_HERE`（本副本）；Windows 机可能另有本地覆盖 |
| 通知默认 dry-run | `NOTIFIER_DRY_RUN` 默认 `"1"`，企微可能“以为发了其实没发” |
| 测试未绿 | 2026-07-13 日报：246 pass / 20 fail（含 REQ-048/057） |

### 建议顺序
1. 封死 P0：止损实卖 + 信号落地 + 串价单一价源  
2. 清单化两套定时器（见 `docs/CRON_JOBS.md`）  
3. OpenClaw 交易相关改 `systemEvent` 直跑脚本，LLM 只做报告  
4. 按 QL-013 把旧入口迁 `legacy/`，根目录只留正式入口  

详细架构债见 `docs/QUANT_OPTIMIZATION_IMPLEMENTATION_PLAN.md`、`docs/QL-013-LEGACY-MIGRATION.md`。

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
- **定时任务**（OpenClaw cron + Windows schtasks，见 CRON_JOBS）

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

> 状态以 `pm.db` 为准（2026-07-14 查询）。`verified` ≠ 生产已稳，只表示有人标过验。

### P0 紧急（真金白银逻辑）
| ID | 标题 | 状态 | 说明 |
|----|------|:----:|------|
| REQ-048 | 止损执行链路 Bug | code-fixed* | 审计/重置已补；等产机挂 bat + QA |
| REQ-057 | 信号 executed 但 0 成交 | code-fixed* | trade 字段口径单测绿 |
| REQ-061 | 龙旗科技移动止损破位未卖 | verified | 结合 cleanup_orphaned 复测 |
| TASK-20260709-2004-001 | buy_zone 参考价/MA10 串价 | code-fixed* | 见 REQ-062 文案修复 |

\* `code-fixed` = 本仓库代码已修，**pm.db 未自动改状态**（等你/QA 验收后标 fixed→verified）。


### P1 待修复 / 复发风险
| ID | 标题 | 状态 | 说明 |
|----|------|:----:|------|
| REQ-011 | 接入 vnpy OmsEngine | pending | 订单成交回放 |
| REQ-043 | 去大模型化 | pending | cron：`agentTurn` → `systemEvent` |
| REQ-058 | 清仓后 threshold_state 悬挂 | verified | 清表过狠可能伤到 REQ-061 |
| REQ-059 | buy_zone 串价（执行侧） | verified | 执行价修了；展示仍见 REQ-062 |
| REQ-060 | news_sentiment price=0 / 无名 | verified | 影子信号脏数据 |
| REQ-062 | 信号文本参考价仍串价 | verified | REQ-059 复发面 |
| REQ-063 | sim_daily_nav 连续缺失 | verified | 日收益核算断档 |

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
- [x] **波段交易日报**：`swing_daily_report.py` — 账户#3 模拟成交 + 赚亏结论 + 实盘挂单建议
- [x] **每日交易台账**：`trade_journal.py` — `pm/trade_journal/` 复盘底稿
- [ ] **波段策略回测**：对 swing 选股逻辑做历史回测
- [ ] **波段信号分级推送**：已并入日报（A/B≥5 才模拟开仓）
- [ ] **波段持仓止损线**：日报按 -5%/+8%，可再写入 positions 字段持久化


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

## 五、已关闭（勿把 P0 误放这里）

- REQ-002 / REQ-003 / REQ-004：采样与通知相关（历史完成）
- REQ-005（旧：总资产显示）— 注意同号另有「观察列表缩略图」P2 仍 testing
- REQ-034 / REQ-044 / REQ-065 / REQ-066：已落地条目

**禁止**：把 REQ-048 / 057 / 061 / TASK-串价 标进本段。状态未绿、单测未过 = 没关。

---

## 六、技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.11+（`pyproject.toml`：`>=3.11,<3.14`；vnpy 建议 Win 上 3.11） |
| 数据获取 | akshare、baostock、腾讯行情、mootdx |
| 数据库 | SQLite（`sim_live_mirror.db` + `pm.db`） |
| 通知 | 企微 webhook（注意默认 dry-run） |
| 定时任务 | OpenClaw Cron（LLM）+ Windows schtasks（`.bat`） |
| 策略/执行 | `quant_core` + `vqlearn` + vnpy/QMT（并行未统一） |
| 回测 | `vqlearn/runners/` + `research/walk_forward.py` + 旧 `backtest.py` |

---

## 七、项目结构（目标收敛态）

```
quant-learn/
├── sim/                    # 模拟盘（现行主链路之一）
├── quant_core/             # 无 IO 核心（目标统一层）
├── vqlearn/                # paper/回测/阈值策略
├── strategies/             # vnpy CTA 策略
├── broker/ gateways/       # 执行与行情
├── notifier/               # 企微
├── runners/                # 正式启动入口（intraday/gui）
├── scripts/                # 运维脚本（应收敛；勿再堆 _tmp）
├── legacy/                 # 旧入口停放处（QL-013）
├── skills/                 # OpenClaw 技能
├── tests/                  # 唯一 pytest 收集目录
├── data/ output/ pm/ docs/
└── config.yaml             # 唯一主配置（目标）
```

**当前现实**：根目录与 `scripts/` 仍大量临时文件；勿把杂物当正式 API。
