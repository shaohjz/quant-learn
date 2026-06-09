# qlib 融合架构

> 把 quant-qlib 整合进 quant-learn 后，整个量化系统单仓库可跑。

## 架构图

```
quant-learn/                                # 主项目（决策、执行、复盘）
├── .venv/                                  # py3.11.9，跑主项目（无 qlib）
├── broker/
│   ├── sim_broker.py                       # 本地 SQLite 模拟撮合
│   └── qmt_broker.py                       # 国金 QMT mini 实盘 broker
├── decision/                               # ★ 新增：双账户决策器
│   └── fusion_engine.py
├── scripts/
│   ├── portfolio_alert.py                  # 阈值警报（已存在）
│   ├── run_fusion_dispatch.py              # ★ 新增：双账户分流执行器
│   ├── test_qmt_e2e_v2.py                  # ★ 新增：QMT mini dry-run
│   └── daily_review.py                     # 每日复盘（升级中）
├── data/
│   └── daily_signals.json                  # ★ 新增：CSI300 全量当日信号
└── research/
    └── qlib/                               # ★ 已合并的 quant-qlib（独立 venv）
        ├── scripts/
        │   ├── run_user_pool.py            # 旧：10 股池
        │   └── run_csi300_predict.py       # ★ 新：CSI300 全池
        ├── docs/
        │   └── integration.md
        └── output/
            ├── signals.json                # 旧 10 股池信号（fallback 用）
            └── csi300_signals.json         # 新 CSI300 全池信号
```

## 双 venv 策略

由于 qlib 的依赖路径深，会触发 Windows MAX_PATH=260 限制，
**qlib 仍然装在独立短路径 venv**：

| Venv | 路径 | 用途 | 是否含 qlib |
|------|------|------|-------------|
| 主 venv | `C:\Users\Administrator\.openclaw\workspace\quant-learn\.venv` | 主项目运行 | ❌ |
| qlib venv | `C:\qq\v` | 训练 / 推理 qlib 模型 | ✅ pyqlib 0.9.7 + lightgbm 4.6.0 |

**主项目调用 qlib 的方式：**

```python
import subprocess
result = subprocess.run(
    [r"C:\qq\v\Scripts\python.exe",
     r"research/qlib/scripts/run_csi300_predict.py"],
    cwd=ROOT,
    capture_output=True,
    text=True,
)
```

或定时任务直接调 `C:\qq\v\Scripts\python.exe`，把产物写到 `quant-learn/data/daily_signals.json`。

## 数据流（每日）

```
21:00 (盘后) │ qlib venv ─► research/qlib/scripts/run_csi300_predict.py
             │              │
             │              ▼
             │        quant-learn/data/daily_signals.json (CSI300 全量)
             │
09:30~14:55 │ 主 venv ─► scripts/portfolio_alert.py
  (盘中)    │              │
             │              ▼ 触发 → output/alert_state.json
             │
14:55-15:00 │ 主 venv ─► scripts/run_fusion_dispatch.py
             │              │ 读 daily_signals.json + alert_state.json
             │              │ → fusion_engine.decide()
             │              ▼
             │   ┌──────────┴──────────┐
             │   ▼                     ▼
             │ QMT 模拟账户        企微推送（仅 5 持仓相关）
             │ 90072426            真实账户 8890461376（人工执行）
             │ (dry_run/真单)
             │
15:30        │ 主 venv ─► scripts/daily_review.py（升级版）
  (复盘)    │   ▶ QMT 模拟账户当日 PnL
             │   ▶ AI 给真实账户的建议命中率
             │   ▶ iwiki 写入
```

## Schema 版本

- v1：原 user_pool 10 股池信号（`research/qlib/output/signals.json`）
- v1.5：fallback —— 用 v1 数据但塞进新管道（仅在 v2 训练失败时使用）
- v2：CSI300 全量信号（`quant-learn/data/daily_signals.json`），新增 `top_k_buy` / `bottom_k_sell` / `metadata.stock_pool_size=300`

## 双账户隔离（硬约束）

- ❌ **真实账户 8890461376** —— 永远不连接、不下单、不 import
- ✅ **QMT 模拟账户 90072426** —— AI 自由下单（dry_run 期间不真发单）
- 真实持仓 5 只 (600330/002256/002453/002342/603601) 的 AI 信号 **仅以企微消息推送给人工**

## 开关

| 状态 | broker.mode | broker.live.dry_run | 行为 |
|------|-------------|----------------------|------|
| 当前（5/19） | sim | true | sim 撮合 + QMT dry-run（不真下单） |
| 5/20 | sim | true | 同上，再观察一天 |
| 5/21 起 | live | false | QMT 模拟账户真下单（仍是模拟资金，不影响真账户） |

切到 live 步骤：

```yaml
# config.local.yaml
broker:
  mode: "live"             # ← sim → live
  live:
    qmt_account: "90072426"
    qmt_path: "D:\\国金QMT交易端模拟\\userdata_mini"
    dry_run: false         # ← true → false
```
