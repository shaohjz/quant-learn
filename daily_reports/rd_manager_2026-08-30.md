# 研发经理日报 2026-08-30

## 一、需求实现进度对账（PM DB + commit 匹配）

PM DB 共 35 项 task：
- **done 33 项**（94.3%），包括全部 8 项 P0
- **blocked 2 项**（#12、#32），无 in_progress/todo

## 二、本周已完成开发项（commit 核对）

| 提交 | 主题 | 类型 |
|---|---|---|
| 7aed85aa | 银行池独立参数段 bank_swing_strategy（min_net_rr 1.2→1.0，可买 0→3 只） | feat |
| 1f07f3c6 | 费率按真实建仓预算试算，修复低价股被最低佣金误杀 | fix |
| 656f6edf | 收窄银行 profile 资金兜底异常 + 补日志 | fix |
| d04b2ff9 | OmsEngine _on_order 状态枚举归一化 | fix |
| b7b68b16 | tasks/REQ 状态对账脚本，纠正 8 项遮蔽状态 | fix(pm) |

## 三、进行中开发项

无代码层进行中项。#12/#32 代码基建已就绪，仅差实盘联调环境。

## 四、Bug 修复情况

- 本周核心修复：银行股低价被最低佣金误杀（费率放大 6~19 倍 → 净盈亏比为负 → 结构性选不出票），已修复并通过 17/17 新增+回归测试。
- **数据面巡检（今日复核）**：#2/#14 类「止损 executed 但未卖出 / 幽灵持仓」缺陷**零复发** —— ghost positions(qty≤0)=0，threshold_state 空（无悬挂记录），8 个持仓均为合法开放仓。
- web/app.py、sim/*.py 全量 AST 解析通过；web:8080 返回 200 健康。

## 五、子研发 agent 使用情况

**未 spawn 子 agent（0 个）**。判断依据：无新功能需求、无代码 bug 需修复；#12/#32 为纯环境阻塞（缺 vnpy/QMT 实盘联调环境），非开发工作量，不应占用并行研发资源。

## 六、遗留风险（需 PM 决策）

- **#12**（P1，vnpy OmsEngine 成交回放）、**#32**（P2，QMT 订单/成交状态流）：代码基建（sim/db.py 事件监听 + sim_orders/sim_fills）均已就绪，自 08-10 悬置超 18 天，根因为无实盘联调环境。**建议 PM 决策：降级 backlog/挂起，或明确实盘资源排期日期**，不应继续占 active WIP。

## 七、工具链问题（非业务 bug）

pytest 9.0.3 + Python 3.14 在 Windows 下 terminal writer 崩溃（"I/O operation on closed file"），导致全量套件无法产出汇总。近期改动模块（bank_swing/ swing_fee_budget/ swing_params）单独跑 17/17 通过。建议后续统一 pip 环境或降 pytest 版本，属环境治理项。

---
**代码变更说明**：本周净增银行波段策略独立参数化、费率试算修正、资金兜底收敛三组改动，均带回归测试；P0 8 项零回退。
