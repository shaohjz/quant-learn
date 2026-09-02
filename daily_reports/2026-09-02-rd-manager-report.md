# 2026-09-02 研发经理·每日研发汇报

> 本地日期 = 2026-09-02（周三，交易日）。时区 Asia/Shanghai。
> 审查基准：`data/pm.db`（tasks 35 条）+ `pm/requirements/*.md` 真源 + `git log` + `data/sim_live_mirror.db`。
> Web 入口 http://21.214.59.210:8080/ 状态 **200 正常**。

## 一、需求实现进度审查

**PM DB `tasks` 表（旧 sqlite 源，35 条）**
- done 33 / blocked 2 / todo 0 / in_progress 0
- P0 8/8 全部 done，零回退
- blocked 仅 2 项：#12（REQ-011 vnpy OmsEngine 成交回放，P1）、#32（REQ-019 QMT 订单流，P2）——均为 prod vnpy/QMT 实盘环境缺失，代码基建已就绪

**markdown 真源（权威，DEPLOYMENT.md 已废弃 pm.db 任务）**
- P0 = 0 open（全部 verified/closed）
- P1 testing = 2 项：REQ-011、REQ-106
- 需求侧无新增 P0 风险

**代码↔需求匹配结论**：commit 记录（今日 `bb63db51`/`ab3aca85` 两个 daily 落盘 + rd-report）与需求闭环一致，无挂账遗漏。

## 二、Bug / 潜在问题审查

| 项 | 判定 | 说明 |
|----|------|------|
| `sim/db.py` `_on_order` 状态映射（昨日已修） | ✅ 已修复 | vnpy Status 枚举串归一化逻辑已就位（`split('.')[-1].upper()`），无脏数据 |
| `config_auto.yaml` +78 行 | ✅ 良性 | 盘中异动扫描自动发现（北京银行 601169、万科A 000002 等观察池条目），非缺陷 |
| `scripts/pm_*.py` 回退依赖 pm.db | ⚠️ 待清理 | 工作区改动重新读写已废弃的 `data/pm.db`，违反 DEPLOYMENT.md「禁止写 pm.db 任务」红线；不阻断今日产物，但合并前须 `git checkout` 还原 |
| **#3 波段仓满仓拦截（P0）** | ⛔ 待决策 | 近 15 日 14 天有买点却因 `max_total_positions=5` 满仓 0 成交；5 仓×1 万 = 5 万恰好等于本金，现金 ~7k 闲置仍判定满仓。属交易核心口径问题，非代码缺陷 |

**结论**：无「今天就能修」的纯代码 Bug。唯一 P0（#3 满仓）触及交易核心仓位/预算口径，按 DEPLOYMENT.md 红线「改交易核心」属禁止自改项，须 owner=quant 决策后走配置/参数流程。

## 三、子研发 agent 使用情况

**未启用（0 个）**。今日无并行开发任务——遗留事项均为 PM 决策/验收收尾（降级决策、P1 testing 结案、假设核对），非可拆分的代码开发。无 Bug 需派发修复。

## 四、代码变更说明

**今日已进 master**（`bb63db51`、`ab3aca85`）：
- 交易台账 / PM 队列 / 测试运维落盘
- 台账 / LLM 日报 / PM 落盘
- 已提交 `daily_reports/2026-09-02-rd-report.md`（主体日报）

**未提交工作区改动**（非本职责提交范围，需 PM 决策）：
- `config_auto.yaml`（+78 行，盘中扫描发现，良性）
- `scripts/pm_daily_report.py` / `pm_inspect.py` / `pm_report.py`（回退依赖 pm.db，建议还原）
- 运行时状态产物：`output/alert_state.json` 等
- 一次性排查脚本 `dev_*.py`（约 20 个，建议清理）

## 五、明日优先（PM 决策项）

1. **P0 #3 满仓拦截**：登记 `pm/bugs/`，评估单笔预算口径（5 仓×1 万恰好满 5 万无余量），owner=quant 拍板提仓位上限或放宽单笔预算。
2. **清理 pm 脚本回退**：`git checkout scripts/pm_*.py` 还原 markdown 真源版本。
3. **关闭 2 项 P1 testing**：REQ-011（vnpy 回放，阻塞于实盘环境）、REQ-106（银行波段，实际已上线 #4 账户）推进结案。
4. **核对假设 H-001/H-002**：`strategy_review.py --close-hypothesis` 结案。
5. **#12/#32 blocked 决策**：prod vnpy/QMT 环境仍缺失，建议正式降级 backlog，结束 21 天悬置。

---
_研发经理日报 · 2026-09-02 · 无新增 P0 代码缺陷，唯一 P0 为交易核心口径决策项，待 PM/owner 拍板。_
