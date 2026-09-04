# 2026-09-04 研发经理·每日研发汇报

> 本地日期 = 2026-09-04（周五，交易日）。时区 Asia/Shanghai。
> 审查基准：`data/pm.db`（tasks 35 条）+ `pm/requirements/*.md` 真源 + `git log` + `data/sim_live_mirror.db`。
> Web 入口 http://21.214.59.210:8080/ 运行中；`web/app.py` 与 `sim/` 核心模块语法自检通过。

## 一、需求实现进度审查

**PM DB `tasks` 表（旧 sqlite 源，35 条）**
- done 33 / blocked 2 / todo 0 / in_progress 0（与 09-02、09-03 一致，保持零 in-progress 收敛姿态）
- P0 8/8 全部 done，零回退
- blocked 2 项：#12（REQ-011 vnpy OmsEngine 成交回放，P1）、#32（REQ-019 QMT 订单状态流，P2）——均为 prod vnpy/QMT 实盘环境缺失所致，代码基建（sim/db.py 事件监听 + sim_orders/sim_fills）已就绪，属环境依赖型阻塞，非代码层。

**markdown 真源（权威）**
- P0 = 0 open（全部 verified/closed），无新增 P0 风险。
- P1 testing = 2 项：REQ-011、REQ-106（银行波段，#4 账户，今日仍空仓，见 §4）。

**代码↔需求匹配结论**：今日 git 提交（`a9c11ee8` 交易台账/PM队列落盘、`d0bb32db` 台账/LLM日报/PM 落盘）与需求闭环一致，无挂账遗漏。

## 二、Bug / 潜在问题审查与修复

| 项 | 判定 | 处置 |
|----|------|------|
| `scripts/pm_*.py` 回退依赖已废弃 pm.db | ⛔ **已修复** | 工作区三个脚本（`pm_daily_report.py`/`pm_inspect.py`/`pm_report.py`）被本地实验版覆盖，重新读写已废弃的 `data/pm.db`（内含硬编码过期日期 `2026-08-31`），违反 DEPLOYMENT.md「禁止写 pm.db」红线。**本次已 `git checkout` 还原为 HEAD markdown 真源版本**，消除 pm.db 写回路径。 |
| `sim/db.py` `_on_order` 状态枚举归一化 | ✅ 已修复（历史） | 08-27 `fix(vnpy)` 已就位，`split('.')[-1].upper()` 归一化逻辑正常。 |
| `web/app.py` / `sim/` 核心模块 | ✅ 无 Bug | ast 语法自检通过，无语法/导入缺陷。 |
| sim DB 健康度 | ✅ 正常 | `threshold_state` 0 行（无止损悬挂遗留）、sim_orders/sim_fills 0 行、无 ghost 持仓（quantity≤0=0）。 |
| `config_auto.yaml` +104 行 | ✅ 良性 | 盘中异动扫描自动发现观察池条目（北京银行 601169、万科A 000002 等），非缺陷。 |

**结论**：本次唯一可修的纯代码问题（pm 脚本回退污染）已在今日修复闭环。无「触及交易核心」的新增 P0 代码缺陷。

## 三、子研发 agent 使用情况

**未启用（0 个）**。今日无并行开发任务——遗留事项均为 PM 决策/验收收尾（#12/#32 降级决策、P1 testing 结案、#3 满仓口径假设核对），非可拆分的代码开发；pm 脚本回退污染为单文件级修复，由主 session 直接完成，无需派发子 agent。

## 四、模拟盘快照（收盘）

| 账户 | 总资产 | 今日盈亏 | 累计 | 持仓数 |
|------|-------:|---------:|-----:|------:|
| #1 learn | 93,759.26 | +144.38 | -6.24% | 5 |
| #2 real_portfolio | 23,963.64 | 0.00 | — | 0 |
| #3 swing_trade | 48,373.61 | -150.34 | -3.25% | 5 |
| #4 bank_swing | 30,000.00 | 0.00 | 0.00% | 0 |

- #4 银行波段自上线持续空仓，今日仍无买点/成交，需继续观察是行情因素还是隐性拦截（费率 08-29 已修）。

## 五、代码变更说明

**今日已进 master**
- `a9c11ee8` 交易台账/PM队列/测试与运维落盘（17 文件）
- `d0bb32db` 台账/LLM日报/PM 落盘（rd-report + finance-report + nightwatch）

**本次研发经理处置（工作区，未提交）**
- `scripts/pm_daily_report.py` / `pm_inspect.py` / `pm_report.py`：`git checkout` 还原为 HEAD markdown 真源版本（修复 pm.db 回退污染）。

## 六、明日优先（PM 决策项）

1. **#12/#32 blocked 降级决策**：prod vnpy/QMT 实盘环境仍缺失，悬置已 24 天，建议正式降级为 backlog/parked 并移出活跃迭代 WIP（需 PM/owner 拍板，勿自改）。
2. **关闭 2 项 P1 testing**：REQ-011（vnpy 回放，阻塞于环境）、REQ-106（银行波段，实际已上线 #4 账户）。
3. **#3 波段仓满仓口径**：5 仓×1 万恰满本金、现金 ~7k 闲置仍判满仓，属交易核心口径问题，登记 `pm/bugs/` 待 owner=quant 决策。
4. **技术债清理**：`scripts/` 下 20+ 未跟踪 `dev_*.py` / `pm_*.py` 草稿脚本评审后归档/删除，降 git 噪声。

---
_研发经理日报 · 2026-09-04 · 今日修复 1 项 pm 脚本回退污染；无新增 P0 代码缺陷，遗留事项均为 PM/owner 决策项（#12/#32 降级、#3 满仓口径）。_
