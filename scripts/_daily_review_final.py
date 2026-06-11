#!/usr/bin/env python3
"""理财经理日报 - 自动创建改进需求 + 推送日报"""
import sqlite3, json, os, subprocess, sys

base = r'C:\Users\Administrator\.openclaw\workspace\quant-learn'
pm_db = os.path.join(base, 'data', 'pm.db')
scripts_dir = os.path.join(base, 'scripts')

# ── 1. 创建 PM 需求 ──────────────────────────────────────────────
conn = sqlite3.connect(pm_db)
cur = conn.cursor()

def next_id():
    cur.execute("SELECT id FROM tasks ORDER BY id DESC LIMIT 1")
    last = cur.fetchone()
    num = int(last[0].split('-')[1]) + 1 if last else 1
    return f"REQ-{num:03d}"

requirements = [
    {
        "type": "story",
        "title": "止损执行链路 Bug：threshold_state 已标记 executed 但 sim_positions 未卖出",
        "description": "2026-05-27 复盘发现：603757 大元泵业趋势破位，threshold_state 状态为 executed（次日开盘确认卖出），但 sim_positions 中该仓位仍然存在（200股，浮亏-13.72%）。\n\n根因：threshold_state 标记执行后，sim_executor 未真正下发卖出指令，或卖出指令被风控拦截但未回滚状态。\n\n修复：1) 在 threshold_state 标记 executed 前增加 sim_positions 实际持仓校验；2) 卖出成功后回调更新 threshold_state；3) 每日复盘自动扫描 'executed' 但仓位仍在的记录并告警。",
        "priority": "P0",
    },
    {
        "type": "story",
        "title": "持仓集中度风控：单票市值占比超过 15% 自动预警并限制新建仓",
        "description": "当前 sim_positions 中 002709 天赐材料市值 26,650，占持仓总市值 94,045 的 28.3%，远超 15% 建议上限。集中度过高风险高，一旦该股破位将严重拖累整体净值。\n\n需求：1) 在自动买入前计算买入后该票占比，超过 15% 则降级为观察单并写入 review_decisions；2) 每日复盘报告标注超限持仓；3) 推送企微预警（单票占比 ≥20% 时）。",
        "priority": "P1",
    },
    {
        "type": "story",
        "title": "sim_daily_nav 数据异常检测：单日收益率超过 20% 自动拦截并告警",
        "description": "2026-05-27 sim_daily_nav 记录 account_id=1 单日收益率 +100.4%（总净值 98,644 → 197,682），现金从 5,373 跳到 103,637，不符合任何正常交易逻辑，疑似模拟账户被重置或数据写入错误。\n\n需求：1) 在写入 sim_daily_nav 前校验 daily_return 绝对值 > 20% 则拒绝写入并写 error_log；2) 检测到异常时自动发送企微告警（@财富经理）；3) 提供 data_audit.py 脚本手动比对 sim_account / sim_positions / sim_trades 数据一致性。",
        "priority": "P1",
    },
]

created = []
for req in requirements:
    rid = next_id()
    cur.execute(
        "INSERT INTO tasks (id, type, title, description, status, priority, created_at, updated_at) VALUES (?,?,?,?,?,?,datetime('now','localtime'),datetime('now','localtime'))",
        (rid, req["type"], req["title"], req["description"], "pending", req["priority"])
    )
    created.append((rid, req["title"], req["priority"]))
    print(f"[PM] 已创建 {rid}: {req['title'][:40]}...")

conn.commit()
conn.close()

# ── 2. 编译日报 ──────────────────────────────────────────────────
report = """📊 理财经理日报 · 2026-05-27

### 📈 今日操作复盘
- 模拟盘：买入 1 笔（万润科技 002654，buy_zone 信号）/ 卖出 0 笔
- 实盘：无操作（TestLoss 测试仓位未动）
- 纪律评分：⭐️⭐️/5

> ⚠️ **严重纪律失效**：603757 大元泵业浮亏 -13.72%，threshold_state 已标记 stop-loss 执行，但 sim_positions 中 200 股仓位仍在，止损卖出并未真正执行。需紧急修复执行链路。

### 📊 仓位分析
- 总仓位：47.6%（现金 103,637 / 总净值 197,682）✅ 非常健康
- 集中风险：最高单票 002709 天赐材料占比 **28.3%**（建议 ≤ 15%）⚠️ 严重超标
- 可用资金：¥103,637（52.4%）✅ 充裕
- 持仓个数：8 只（建议 ≤ 6）→ 已满，新买入将被风控拒绝 ✅

### 🔍 策略诊断
- 今日触发但未执行信号：1 个（603757 趋势破位止损 → 标记 executed 但未实际卖出）❌
- 浮亏 > 5% 持仓：603757 大元泵业 -13.72%、002654 万润科技 -5.76%、002149 西部材料 -4.71%
- 浮盈 > 5% 持仓：600310 广西能源 +15.48% ✅（take_profit 已 armed，明日确认后触发止盈）
- 数据异常：sim_daily_nav 记录今日收益率 +100.4%，现金异常跳增，疑似账户重置 ⚠️

### 💡 改进建议（已自动建需求）
"""

for rid, title, pri in created:
    report += f"- {rid}: {title}（优先级 {pri}）\n"

report += """
### 📊 明日重点关注
1. 🔴 **603757 大元泵业**：浮亏 -13.72%，止损未执行，明日开盘必须手动/自动卖出，不能再拖
2. 🟡 **600310 广西能源**：take_profit armed，明日收盘确认 ≥ 5.76 则触发止盈卖出，关注
3. 🟡 **002709 天赐材料**：占比 28.3% 严重超标，建议部分减仓至 15% 以内
4. 🔵 **数据异常排查**：sim_daily_nav 现金跳增，需确认模拟账户是否被重置，避免历史收益数据失真

---
> 以上为职业理财经理第三方视角复盘，仅供决策参考。市场有风险，投资需谨慎。
"""

print("\n=== 日报内容 ===")
print(report)

# ── 3. 推送日报到企微 ────────────────────────────────────────────
notify_py = os.path.join(scripts_dir, 'notify.py')
cmd = [sys.executable, notify_py, '--type', 'markdown', '--content', report]
print("\n[notify] 发送日报到企微群...")
result = subprocess.run(cmd, capture_output=True, text=True, cwd=base)
print("stdout:", result.stdout[:500])
print("stderr:", result.stderr[:500])
print("returncode:", result.returncode)
