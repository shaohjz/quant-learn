# 实时监控全景（整个量化项目）

> 你一直不清楚的点，浓缩在这里。  
> **结论先说**：项目**能**盘中实时盯，也**有**大盘/宽基扫描代码；但默认容易只挂收盘波段，导致感觉「不够量化」。  
> 配套：`DEPLOYMENT.md` / `CRON_JOBS.md` / 项目根 `README.md`  
> 更新：2026-07-15

---

## 1. 一句话地图

```
盘前 ~08:30     宽基选股扫描（沪深300+中证500 ≈800 只）→ Top 候选
盘前 ~08:40     SwingPool 动态稳定池 Top20 + swing_auto 盘前机会推企微
盘中 每10分     QuantPulse = 真仓阈值 + 波段机会(扫Top20) + 指数（主心跳）
盘中 每30分     （可选）全市场异动扫描 ≈800 只
收盘 16:05      波段模拟成交 + 赚亏结论 + 挂单复盘
收盘 16:15      交易台账 → pm/trade_journal/
```

**「每天会不会实时扫大盘？」**

| 问题 | 答案 |
|------|------|
| 有没有扫大盘的代码？ | **有**。`morning_scanner` / `intraday_scanner`（约 800 只：沪深300+中证500） |
| 产机是否一定在跑？ | **看 schtasks 开没开**。文档曾把它们标「可关」，所以很多人以为没有 |
| 是 tick 级毫秒实盘吗？ | **不是**。默认是「计划任务轮询」分钟级（够个人挂单） |
| 真正 tick 实盘路径？ | `vqlearn_live` / vnpy+QMT 订阅（更重，可按需开） |

---

## 2. 三层监控（建议你都理解）

### L1 — 你的钱相关（必开）

| 脚本 | 盯什么 | 频率 | 推什么 |
|------|--------|------|--------|
| `quant_pulse.py` | **统一入口**：调 portfolio_alert + swing_intraday + 指数 | 盘中 10 分 | 主推送 |
| `portfolio_alert.py` | `config.yaml` 里 **real_portfolio_rules + watchlist** | （由 Pulse 调） | 你的股破止损/到买区 |
| `swing_pool_builder.py` | 沪深300+中证500 → Top20 稳定池 | 盘前 08:40 | 建池；同 bat 调 `swing_auto` 推企微 |
| `swing_auto.py` | 稳定池 A/B 机会 + 盈亏比 | 盘前 08:40（跟 SwingPool） | 盘前波段扫描报告 |
| `swing_intraday_watch.py` | 动态稳定池 + 波段账户#3 | （由 Pulse 调） | 好价买/止盈止损提醒，**并同步模拟成交** |
| `swing_daily_report.py` | 全日波段模拟 | 16:05 | 赚亏结论 |
| `trade_journal.py` | 全账户成交+持仓 | 16:15 | 复盘台账 |

### L2 — 市场发现（建议开）

| 脚本 | 盯什么 | 频率 | 推什么 |
|------|--------|------|--------|
| `scanner_with_fallback.py`（→ morning / lite） | ≈800 只宽基成分 | **盘前 ~08:30** | Top 候选进企微 / `output/scan/` |
| `intraday_scanner.py` | ≈800 只异动 | **盘中每 30 分** | 量价突破等 → 可写入 `watchlist.auto_discovered` |

注意：东财/AKShare 在部分网络会挂 → fallback 到 `scanner_lite`（约 30 只）。

### L3 — 连续行情引擎（可选，更「量化」）

| 脚本 | 说明 |
|------|------|
| `vqlearn_live_runner.bat` | 09:25 起跑 paper 策略，tick/分钟级规则 |
| `runners/run_intraday.py` | vnpy+QMT 主循环（要 QMT 登录） |

---

## 3. 「实时」到底多实时？

| 模式 | 延迟 | 适用 |
|------|------|------|
| schtasks 轮询 | 5–10 分钟 | **个人挂单建议（推荐主路径）** |
| OpenClaw cron | 同上，还吃 LLM 网络 | 别用于交易触发 |
| vqlearn / vnpy 常驻 | 秒级～分钟 | 学习仓自动模拟 |
| QMT 官方推送 | 接近真实行情 | 真券商联动时再上 |

你要「价格合适盘中提醒」→ **开 L1 轮询就够**。  
你要「全市场每天找新票」→ **开 L2 盘前扫描**。  
你要「策略自动跟价」→ 再考虑 L3。

---

## 4. 推荐产机开关（想更高实时性）

### 必开

```bat
QuantLearn_PortfolioAlert     REM 真仓阈值
QuantLearn_SwingIntraday      REM 波段盘中机会（每10分）
QuantLearn_SwingDaily         REM 16:05 结论
QuantLearn_QuantPulse         REM 统一脉搏（下面新建，一次跑 L1）
```

### 建议开（回答「有没有扫大盘」）

```bat
QuantLearn_MorningScan        REM 08:30 宽基800扫 → Top
QuantLearn_IntradayScanner    REM 盘中30分 异动（可接受消息稍多）
```

### 按需

```bat
QuantLearn_VqlearnLive        REM 阈值学习仓常驻
```

统一脉搏脚本（盘中一次调用搞定 L1）：

```bat
scripts\quant_pulse_runner.bat
→ python scripts\quant_pulse.py
   ├─ portfolio_alert
   └─ swing_intraday_watch
```

---

## 5. 数据流（你挂单怎么接到）

```
行情（腾讯/AKShare）
    │
    ├─ morning/intraday scanner ──► 候选/观察池 ──►（人工或自动写入 watchlist）
    │
    ├─ portfolio_alert ──► 企微：你的股到价了
    │
    └─ swing_intraday + swing_daily ──► 企微：波段买/卖建议 + 赚亏
              │
              └─ 你自己在券商挂单（默认不实盘代下）
```

---

## 6. 常见误解

| 误解 | 事实 |
|------|------|
| 「项目从不扫大盘」 | 代码有 800 只扫；没开任务 = 等于没扫 |
| 「16:05 日报 = 全部监控」 | 日报只覆盖波段模拟结论 |
| 「有 vnpy 就一定实时」 | 要进程在跑且 QMT/订阅正常 |
| 「关掉 IntradayScanner 就没机会」 | 波段池 + 观察池阈值仍在盯；只是少了全市场异动发现 |

---

## 7. OpenClaw 检查口令

```text
1. schtasks /query | findstr QuantLearn
2. 确认存在：PortfolioAlert、SwingIntraday、SwingDaily；建议有 MorningScan
3. 试跑：python scripts/quant_pulse.py --force --no-push
4. 试跑：python scripts/scanner_with_fallback.py（看早盘扫能否出 Top）
5. 把结果写入 pm/ops/今日-realtime.md
```
