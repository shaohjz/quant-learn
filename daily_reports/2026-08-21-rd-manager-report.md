# 研发经理日报 — 2026-08-21（周五）

> 视角：研发经理。锚定 2026-08-21 收盘 + 当日 commit 记录 + `data/pm.db` 任务队列 + `tests/` 实测。

## 1. 需求实现进度（核对 PM DB ↔ 代码 commit）

- **PM 队列**：`data/pm.db` 共 35 条 task —— done 27 / in_progress 5 / todo 3。
- **进行中（in_progress）5 项**：#27 双账户复盘异常提醒、#28 策略信号盈亏自动统计、#29 复盘要点自动获取、#30 交易纪律打卡评分、#31 REQ-005 观察列表 K 线缩略图。
- **待办（todo）3 项**：#32 QMT 订单/成交状态流、#12 接入 vnpy OmsEngine 回放、#13 盘盯 cron 去大模型化（agentTurn→systemEvent）。
- **今日代码主线已完成**：`cecd41e2`（银行股专用波段 #4 + REQ-058 清仓级联失效 threshold）、`547d0b90`（部署报告）。新增 `quant_core/bank_swing_pool.py`、`scripts/bank_swing_daily.py`、`scripts/patrol_orphan_thresholds.py` 等，账户 #4 bank_swing 已建并冒烟全绿。

## 2. Bug 修复（今日新发现 + 已完成）

| # | Bug | 状态 |
|---|-----|------|
| 1 | `tests/test_bank_swing_daily.py::test_apply_bank_profile_overrides` 报 `ModuleNotFoundError: No module named 'swing_daily_report'`（测试未把 `scripts/` 加入 sys.path） | ✅ 已修复 |
| 2 | `QuantLearn_DailyGitSync` / `DailyGitSyncEvening` 以 SYSTEM 身份运行 → `git push` 报 `Host key verification failed`（Last Result=3，持续失能） | ✅ 已修复 |

**修复细节**：
- Bug 1：在测试头部补 `sys.path.insert`（对齐 `test_req006_quick_actions.py` 既有写法），修后 6/6 全绿。
- Bug 2：root cause 是 SYSTEM 账户 SSH 不读管理员 `.ssh`。在 `daily_git_sync_runner.bat` 显式注入 `GIT_SSH_COMMAND`（`StrictHostKeyChecking=accept-new` + 前向斜杠的 `UserKnownHostsFile`/`-i` 路径），并修正路径为前向斜杠以消除 ssh 的 "Identity file not accessible" 告警。已本地 cmd 实测 `git ls-remote` 成功。

## 3. 测试与代码变更说明

- **新增/改动提交（已 push master）**：
  - `ea9bd28c` fix(ci): bank_swing 测试 import 路径 + DailyGitSync SSH known_hosts
  - `35d6756d` fix(ci): DailyGitSync SSH 前向斜杠路径（SYSTEM-safe）
- **测试结果**：`test_bank_swing_daily.py` + `test_req058_expire_on_flat.py` → **6 passed**（修复前 1 failed）。
- **⚠️ 全量测试套件存在环境性收集中断**：`pytest 9.0.3 + Python 3.14` 跑 `tests/` 全集时在 teardown 阶段抛 `ValueError: I/O operation on closed file`，导致只收集 16 条即中断（非项目业务 bug，单文件跑均正常）。另 `test_position_limit.py` 会 `os.remove(data/sim.db)`（非 live mirror），`test_fetch_sim_snapshot_from_mirror` 读真实 mirror 断言陈旧值 —— 属测试隔离缺陷，建议后续专项处理。
- **已知残留风险**：`output/pm_web.log` 被 pm_web 进程锁住，`git reset --hard` / `git pull --rebase` 间歇报 `unable to unlink ... Invalid argument`（需在 DailyGitSync 前确保 pm_web 进程不占用该日志文件）。

## 4. 子研发 agent 使用情况

- 本次任务为单点修复（2 个小 bug），**未启动子研发 agent**（无并行开发需求，0/10）。
- 如后续推进「全量测试套件隔离整改」或「#31 REQ-005 K线缩略图」开发，可派子 agent 并行。

## 5. 明日优先

1. **验证 DailyGitSync 修复生效**：明晚 18:45 / 20:30 schtasks 跑后确认 `Last Result=0`（今晚 20:30 Evening 是首个验证点）。
2. `tests/` 全量套件收集中断 + 测试隔离缺陷整改（`test_position_limit` 删真实库、mirror 断言陈旧）。
3. 推进 in_progress 5 项（尤其 #31 REQ-005）与 todo 3 项排期。
4. 补 08-20 缺失的 finance-report（08-21 已补写）。

---
_生成：研发经理日报 Agent · 2026-08-21 20:15 快照（非投资承诺）_
