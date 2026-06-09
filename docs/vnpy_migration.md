# vnpy 迁移说明（2026-05-19）

## 为什么迁移
原项目自研框架（`backtest.py` + `sim/engine.py` + `scripts/portfolio_alert.py`）能跑，
但事件总线、订单状态机、回测引擎都是手写的，加一只新券或一个新策略要改多个文件。
迁移到 [vnpy 4.x](https://www.vnpy.com/) 之后：
- 标准事件总线 + OmsEngine 管订单 / 持仓 / 资金
- CtaStrategyApp 提供策略生命周期（on_init / on_start / on_tick / on_bar / on_stop）
- 自带 PySide6 桌面 GUI（K 线 / 委托 / 持仓 / 资金一目了然）
- 回测、组合策略、实盘共享同一套策略代码
- 老代码全部保留，新代码 wrap 一层即可，零回归风险

## 新架构

```
quant-learn/
├── apps/                    ← vnpy 主引擎工厂
│   └── intraday_app.py
├── gateways/                ← vnpy 网关层
│   ├── qmt_gateway.py       ← 自封装的 QMT mini gateway（基于 xtquant 直连）
│   └── qmt_config.json
├── strategies/              ← 策略模块（老 + 新）
│   ├── threshold_alert_strategy.py   ← 新：vnpy 版 portfolio_alert
│   ├── fusion_strategy.py            ← 新：vnpy 版 fusion_engine
│   ├── sma_cross.py / macd_strategy.py / composite_v2.py …  ← 老（保留）
├── notifier/                ← 企微推送统一封装
│   └── wecom_notifier.py
├── runners/                 ← 启动器
│   ├── run_intraday.py      ← 盘中盯盘（无 GUI）
│   ├── run_gui.py           ← 桌面 GUI
│   └── run_backtest.py      ← 回测脚手架
├── scripts/
│   ├── test_vnpy_qmt.py     ← QMT 链路最小验证
│   ├── daily_review_vnpy.py ← 双账户对比（脚手架）
│   └── portfolio_alert.py / sim_executor.py / …  ← 老（保留作为对照）
├── decision/                ← 老融合引擎（被 fusion_strategy 引用，保持不动）
├── broker/                  ← 老 broker 层（保留，sim 25000 仍走它）
└── sim/                     ← 老 sim 引擎（保留）
```

## 启动命令

### 盘中盯盘（无 GUI，**最常用**）
```powershell
cd C:\Users\Administrator\.openclaw\workspace\quant-learn
.venv\Scripts\python.exe -m runners.run_intraday
```
默认 dry_run（不真发单）。要真发单加 `--live`。
要测试只跑 N 秒加 `--duration 30`。

### 桌面 GUI（按需）
```powershell
.venv\Scripts\python.exe -m runners.run_gui
```
启动 PySide6 桌面端，需要 Windows 桌面会话。

### 回测（脚手架）
```powershell
.venv\Scripts\python.exe -m runners.run_backtest --code 600330 --start 20240101 --end 20241231
```
⚠️ K 线数据需要先用 xtquant 拉本地，再注入 vnpy database — 当前是脚手架，未跑通。

### 链路验证
```powershell
.venv\Scripts\python.exe scripts\test_vnpy_qmt.py
```
5 秒内 QMT trader 连上 + 订阅 600330 → 成功打 "✅ QMT trader 连接成功"。

## 双账户运行示意

```
┌─────────────────────────────────────────────────────────┐
│  vnpy MainEngine + EventEngine                         │
│  ┌───────────────┐    ┌─────────────────────────┐      │
│  │ QmtGateway    │    │ CtaStrategyApp          │      │
│  │ (mini 90072426) ─→ │ ┌────────────────────┐ │      │
│  │ dry_run=True   │    │ │ alert_600330 ...   │ │  人工建议  │
│  └───────────────┘    │ │ ThresholdAlert ×10 │─→─企微推送  │
│                        │ └────────────────────┘ │           │
│                        │ ┌────────────────────┐ │           │
│                        │ │ fusion_002709 ...  │ │  自动执行  │
│                        │ │ FusionStrategy ×5  │─→─QmtGateway│
│                        │ └────────────────────┘ │           │
│                        └─────────────────────────┘           │
└──────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  老 sim 引擎（保留作为 25000 元对照组）                       │
│  scripts/sim_executor.py + sim/engine.py + sim.db           │
└─────────────────────────────────────────────────────────────┘
```

持仓 5 只（600330 / 002256 / 002453 / 002342 / 603601）→ 仅推送企微（real_advisor）
观察池 5 只（002709 / 002149 / 002156 / 605006 / 603757）→ vnpy 引擎可自动下单到 QMT mini

## 已知坑

1. **vnpy_xtquant 不可用** ：PyPI 没 release，git+ 安装在当前环境失败（无 git）。
   → 自封装 `gateways/qmt_gateway.py`，直接调 `xtquant`（与 broker/qmt_broker.py 同源）。
2. **真实账户 8890461376 硬隔离** ：FORBIDDEN_ACCOUNTS 在 gateway 和 broker 都写了，连都连不上。
3. **dry_run 默认开** ：`run_intraday` / gateway 默认 `dry_run=True`，要真发单必须显式 `--live`。
4. **企微推送默认 dry-run** ：`NOTIFIER_DRY_RUN=1` 是默认环境变量，要真推必须 `set NOTIFIER_DRY_RUN=0`。
5. **回测数据缺失** ：`runners/run_backtest.py` 是脚手架，K 线需要 xtquant → vnpy db 的注入流程，待补。
6. **GUI 需要桌面会话** ：纯 SSH/RDP 文本模式跑不起来 PySide6。
7. **去重是内存级** ：`ThresholdAlertStrategy` 同阈值同日去重在内存里，进程重启会重新触发；
   要持久化复用 `output/alert_state.json`（未做）。

## 老代码去向
- 全部保留。不删除任何 .py 文件。
- 老 `scripts/portfolio_alert.py` 仍可独立 cron 跑，作为新策略的对照组。
- 老 `scripts/sim_executor.py` + `sim/engine.py` 仍是 25000 元 sim 账户的执行链路。

## 接下来怎么用（明天 5/20 早盘）

1. **9:15 前**：手工启动 QMT 客户端 → 登录模拟账户 90072426
2. **9:25 前**：在 PowerShell 跑：
   ```powershell
   cd C:\Users\Administrator\.openclaw\workspace\quant-learn
   .venv\Scripts\python.exe -m runners.run_intraday
   ```
3. **盘中**：进程会持续打 log，命中阈值就推到企微（dry-run 模式只 print，要真推改 NOTIFIER_DRY_RUN=0）
4. **15:05 后**：Ctrl+C 停掉，跑复盘：
   ```powershell
   .venv\Scripts\python.exe scripts\daily_review.py     # 老复盘
   .venv\Scripts\python.exe scripts\daily_review_vnpy.py  # 新复盘脚手架
   ```
5. **要看 GUI**：单独开一个窗口
   ```powershell
   .venv\Scripts\python.exe -m runners.run_gui
   ```
   不影响盘中后台 runner。

## 真要切换到 live（**慎用**）
1. 启动命令加 `--live`，并显式 `set NOTIFIER_DRY_RUN=0`
2. 第一笔单建议用很小的量（100 股 ETF）跑通 send_order → 成交回调链路
3. 真实账户 8890461376 永远不要进 `qmt_config.json`，已硬拦截
