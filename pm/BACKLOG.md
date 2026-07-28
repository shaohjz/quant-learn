# PM Backlog

> 自动生成于 2026-07-28 20:48:11（`pm_cli list --write-backlog`）。真源为各 REQ/BUG markdown。

| ID | 类型 | 状态 | 优先级 | 标题 |
|----|------|------|--------|------|
| REQ-061 | bug | verified | P0 | 龙旗科技(603341)移动止损已破位但未执行卖出，持仓悬挂 |
| REQ-048 | story | verified | P0 | 止损执行链路 Bug：threshold_state 已标记 executed 但 sim_positions 未卖出 |
| REQ-057 | story | verified | P0 | 盘中14信号executed但0笔买入成交：信号-执行链路断裂复发 |
| REQ-059 | bug | verified | P0 | buy_zone 串价 bug (TASK-20260709-2004-001) 仍 testing，已致 002709 实际止损亏损，需加急验证闭环 |
| REQ-068 | bug | verified | P0 | 止损执行链路 P0 需求(REQ-048/REQ-057)自 06-08 起长期停留在 testing 未闭环验收，且今日 sim_positions 为空却存在 pending 的跌破止损未卖出记录(TASK-20260717-2004-001)，需推动验收或确认已修复 |
| REQ-069 | bug | verified | P0 | REQ-069: sim_daily_nav 日表 07-20 learn(acc1) 记录未反映当日建仓，market_value=0 失真 |
| REQ-101 | bug | verified | P0 | 止损分批残留 100 股（网宿/汤臣/京东方） |
| REQ-105 | bug | verified | P0 | buy_zone 触发阈值脏（天赐47.66/莲花11.75） |
| TASK-20260716-2004-001 | bug | closed | high | sim_positions.pnl_pct 字段被放大100倍（展示性数据错误） |
| TASK-20260716-2004-002 | bug | verified | high | trailing stop 止损价未上移，全部等于/低于成本价 |
| TASK-20260709-2004-001 | bug | verified | high | buy_zone 信号参考价/MA10 价系统性错乱（002709/600021/001896 串价） |
| REQ-011 | story | pending | P1 | 接入vnpy OmsEngine实现详细订单成交回放 |
| REQ-043 | story | pending | P1 | 量化通知/盘中盯盘 cron 去大模型化 — agentTurn → systemEvent |
| REQ-058 | bug | verified | P1 | 持仓清仓后 threshold_state 悬挂记录未自动失效（002709 案例） |
| REQ-060 | bug | verified | P1 | news_sentiment 影子信号 price=0 且 stock_name 未解析（名称=代码），全样本系统性缺陷 |
| REQ-063 | bug | verified | P1 | sim_daily_nav连续缺失(07-11/07-12/07-13无记录)，无法精确核算每日收益 |
| BUG-20260710 | bug | verified | P1 | daily_review / generate_next_watchlist 在 Windows 下因 GBK 编码崩溃 |
| REQ-065 | bug | verified | P1 | 新账户 swing_trade 建仓 600809 山西汾酒未初始化移动止损(trailing_stop=NULL) |
| REQ-066 | bug | verified | P1 | sim_daily_nav 日表再次缺失 learn 账户(acc1) 07-14/07-15 记录，每日收益无法精确核算 |
| TASK-20260717-2004-001 | bug | pending | P1 | 晶方科技(603005)现价31.33已跌破移动止损31.56但持仓未卖出 |
| REQ-062 | bug | verified | P1 | buy_zone/buy_strong信号文本参考价仍串价(REQ-059标fixed但展示未修复) |
| REQ-070 | risk | closed | P1 | REQ-070: 京东方A(000725)浮亏-6.71%紧贴移动止损(0.14元/1.40%)，需明日开盘重点监控 |
| REQ-071 | bug | verified | P1 | REQ-071: 建仓当日 sim_daily_nav 未回写 acc1(learn) 净值，且复盘缺建仓盈亏归因 |
| REQ-100 | bug | verified | P1 | strategy_shadow_signals 停更 / swing acc3 持仓价不刷新 |
| TASK-20260716-2004-003 | task | verified | medium | TASK-20260709-2004-001 验收退回后状态未回退，应置回 testing/open |
| TASK-20260718-2003-001 | bug | open | medium | 清仓后 sim_positions 残留记录未清理（龙旗科技603341、山西汾酒600809 数量=0仍留存） |
| REQ-020 | story | testing | P2 | 双账户复盘支持交易异动或异常提醒 |
| REQ-030 | story | testing | P2 | 支持自动统计策略信号触发的交易盈亏并在复盘中展示 |
| REQ-015 | story | testing | P2 | 支持自动获取用户手工填写的复盘要点分析 |
| REQ-027 | story | testing | P2 | 支持交易纪律打卡与知行合一评分 |
| REQ-005 | story | testing | P2 | REQ-005: 观察列表K线缩略图 |
| REQ-019 | story | pending | P2 | 支持实时同步并展示QMT订单/成交状态流 |
| REQ-047-TEST | story | closed | P2 | 测试自动建需求机制 |
| REQ-064 | story | verified | P2 | 评估 #2 real_portfolio 长期空仓策略有效性 |
| REQ-067 | story | verified | P2 | 京东方A(000725)距移动止损仅0.5%且浮亏-7.6%，需明日开盘重点监控是否触发止损 |
