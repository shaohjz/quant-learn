# 2026-09-16 产机时钟配额停摆 + VqlearnLive rc=3 根因定案（3-windows）

> 两个独立故障叠加，导致「量化交易每天稳定跑」自 9-15 傍晚起全面停摆。本文为事故记录与恢复验证，供 PM/运维复核。
> VqlearnLive 的 bat 修复本体（CRLF + 单行 if + .gitattributes 规则）由 TES-23 工作流完成，另行提交；本文附独立复现与验证证据。

## TL;DR

1. **VqlearnLive rc=3（自 7-28 每天）**：runner bat 为 UTF-8 编码 + LF(Unix) 行尾。cmd 以 GBK 代码页解析批处理时，
   UTF-8 中文注释的尾字节与 `0x0A` 组成合法 GBK 双字节字符，「吃掉」换行 → 行粘连、命令拦腰截断。
   bat 从未执行到 python 行：exit 3、零日志。7-28 20:41 git 回迁写入、20:50 任务重建，**从重建第一天起就坏**。
2. **prod_clock 时钟停摆（自 9-15 16:20）**：9-14 挂的 OpenClaw cron `quant-prod-clock` 实为 **agentTurn（LLM）**，
   每 10 分钟一 tick、一天 100+ 次模型调用，打爆平台「定时任务 50 次/天」配额。9-15 16:20 起连续 9 次
   `rate_limit` 失败后停摆；19:15 守夜与 20:00 日报被连坐禁用（各 5 连错）。**9-16 全天（至 12:58）零时钟产物**：
   无 MorningScan / SwingPool / Pulse，stamps 无 2026-09-16 目录。

## 证据

### A. VqlearnLive rc=3 完整复现（12:31，产机）

- 原 bat 首字节 `40 65 63 68 6F 20 6F 66 66 0A` = `@echo off` + **LF**（无 BOM、无 CR）；全文件无 CRLF。
- 从 `C:\Windows\System32`（任务计划默认起始目录）执行原样字节（仅 `--timeout 20400`→`60`）：
  输出 `'gy'/'trading'/'og' 不是内部或外部命令`、`The system cannot find the path specified`，
  **EXITCODE=3**，日志未动——与每日 09:25 Last Result=3、日志冻结 06-11 的现场完全一致。
- 修复后 bat（CRLF + 单行 if）非侵入验证（`--help` 变体、重定向临时文件）：**PARSE_TEST_EXIT=0**，日志正常生成。
- 12:58 `schtasks /run /tn QuantLearn_VqlearnLive` 正式复跑：python 启动，`output\vqlearn_live.log`
  恢复写入（12:58:12 起实时 TICK 行情、68 个 ThresholdAlertStrategy 实例加载；13:05 已 212KB）。
  预计 ~18:38 退出，届时 Last Result 应更新为 0；明日 09:25 起每日正常。
- 12:49/12:54 工作流曾两次直起 python（未经 bat，规范日志不落盘）；13:00 已停掉直起实例，
  保留 schtasks 通道单实例，避免影子信号双写。

### B. 时钟配额停摆（OpenClaw cron 状态 + 机器日志）

- `openclaw cron list`：`quant-prod-clock` enabled=false，consecutiveErrors=9，
  lastError=`FailoverError: 定时任务调用频率过高，已超过 50 次/天`（最后一次尝试 9-15 20:42）。
- `守夜-验收台账推送`、`pm-agent-daily-report` 同因 rate_limit 连坐禁用（各 5 连错，9-15 21:18 批量置灰）。
- `output\prod_clock.log` 最后一条业务 tick 为 9-15 16:10:11（journal RC=0）；此后无任何 tick。
- stamps：`2026-09-15` 缺 close / strategy_review / git_sync / git_sync_evening；`2026-09-16` 目录不存在。
- 讽刺注脚：`prod_clock_runner.bat` 头部注释本就写着「**禁止做成 LLM agentTurn**」。

## 修复动作（12:40–13:05，3-windows 产机）

| # | 动作 | 结果 |
|---|------|------|
| 1 | 重建 `schtasks \QuantLearn_ProdClock`：工作日 08:25 起 PT10M 重复 PT12H35M（至 21:00）、S4U 后台（不依赖登录会话）、StartWhenAvailable、ExecutionTimeLimit PT30M、电池策略关闭 | 注册成功，Next Run 13:05 |
| 2 | 时钟冒烟 `schtasks /run` | 12:59:42 tick 落 `prod_clock.log` ✅ |
| 3 | 13:05 自然 tick | **RUN pulse**（13:00–14:50 窗口），盘中链路恢复 ✅ |
| 4 | OpenClaw `quant-prod-clock` cron 永久禁用 + 描述注明废弃原因（防误启） | ✅ |
| 5 | 重新启用 `守夜-验收台账推送`（19:15）、`pm-agent-daily-report`（20:00） | ✅ 今晚恢复；每日仅 2 次 LLM 调用 |
| 6 | VqlearnLive 经 schtasks 通道正式复跑 | 12:58 起运行中 ✅ |
| 7 | DEPLOYMENT.md / CRON_JOBS.md 同步（时钟= schtasks 唯一入口） | ✅ 随本提交推送 |

## 今日余下时间线（预期）

- 13:05–14:50 Pulse 每 10 分（schtasks 时钟）；
- 16:00 swing_daily / bank_swing、16:10 journal、16:20 close、16:30 strategy_review；
- 18:40 / 20:30 GitSync 推 master；19:15 守夜验货；20:00 日报落盘。
- **今日已错过的**：MorningScan（08:30）、SwingPool（08:40）——时钟当时已死，窗口不补跑；
  盘中 Pulse 下午用的是 9-15 波段池（`latest.json`），质量可接受，明早自动刷新。

## 遗留风险与建议（待 PM/运维拍板，未擅动）

1. **其余 30+ 个 runner bat 仍是 UTF-8+LF**（含 `swing_pool_builder_runner.bat`——9-14 同样 rc=3）。
   当前多数「侥幸能跑」（中文尾字节恰好没吃掉关键换行），任何一次 git 变更都可能复发。
   建议：`.gitattributes` 从单文件规则扩成 `*.bat text eol=crlf` + 工作区一次性 CRLF 化 + bat 注释去中文。
2. **VqlearnLive 任务仍为 InteractiveToken**（依赖 console 登录会话；本机 console 会话自 7-13 常驻，暂无碍）。
   建议参照 ProdClock 迁 S4U。
3. **失败告警仍缺**：bat 失败只留 rc，无企微告警（本次 3 个月无人察觉即因此）。建议按运维运营方案第 5 条落地：
   失败自动保留日志尾行 + 退出码并推企微。
4. TaskScheduler 操作日志默认关闭（本次排查无 09:25 历史事件可查）；可在任务计划 GUI 开启 Operational Log。

## 附录：QuantLearn_ProdClock 任务 XML（全文）

```xml
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>3-windows 产机时钟：工作日 08:25 起每 10 分钟跑 prod_clock_runner.bat，至 21:00。2026-09-16 起替代 OpenClaw agentTurn 时钟（quant-prod-clock 因 LLM 50次/天配额停摆，见 pm/ops/2026-09-16-clock-quota-outage.md）。OpenClaw 侧同名 cron 保持禁用，禁止双开。</Description>
    <Author>21_214_59_210\Administrator</Author>
    <URI>\QuantLearn_ProdClock</URI>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-21-3306313210-2103341984-1874234270-500</UserId>
      <LogonType>S4U</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Priority>7</Priority>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
  </Settings>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-09-16T08:25:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <WeeksInterval>1</WeeksInterval>
        <DaysOfWeek>
          <Monday />
          <Tuesday />
          <Wednesday />
          <Thursday />
          <Friday />
        </DaysOfWeek>
      </ScheduleByWeek>
      <Repetition>
        <Interval>PT10M</Interval>
        <Duration>PT12H35M</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </CalendarTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts\prod_clock_runner.bat</Command>
      <WorkingDirectory>C:\Users\Administrator\.openclaw\workspace\quant-learn</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
```

---
*3-windows（21_214_59_210）· 2026-09-16 13:08 · 关联：TES-23（VqlearnLive 修复）、TES-29（本事故卡）*
