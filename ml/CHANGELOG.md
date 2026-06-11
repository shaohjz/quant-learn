# quant-qlib · CHANGELOG

## 2026-05-19 — v0.1 Bootstrap

由子 agent `quant-qlib-bootstrap` + 主线 agent 联合完成。

### 新增

- 项目脚手架 `quant-qlib/`（独立于 `quant-learn`）
  - 独立 venv：`C:\qq\v`（短路径绕开 Windows MAX_PATH=260）
  - Python 3.11.9（scoop 安装）
  - 独立 git 仓库（待初始化）
- 安装 `pyqlib`（PyPI 版本）
- 下载 qlib 中国 A 股日频数据（`~/.qlib/qlib_data/cn_data`）
  - 数据范围：1999-11-10 到 **2020-09-25**（这是 qlib 公开数据集的边界）
- 跑通 qlib 官方 quickstart（CSI300 + LightGBM + Alpha158）
  - 基准（CSI300）：年化 26.87%，最大回撤 -17.2%
  - **超额（含成本）年化 8.53% / IR 1.01**
  - **IC = 0.0368**，Rank IC = 0.0442
  - **ICIR = 0.29**，Rank ICIR = 0.34
  - 产物：`output/qlib_demo_result.txt`、`output/run_demo.log`
- 用户股池 LightGBM 回测（10 只：5 持仓 + 5 观察）
  - 训练池：CSI300（300 只样本）
  - 投影池：用户 10 只（避免 IC 失真）
  - 训练窗口：2014-01 → 2018-12
  - 验证窗口：2019-01 → 2019-06
  - 测试窗口：2019-07 → 2020-09
  - 产物：`output/user_pool_result.txt`、`output/signals.json`
- **signals.json 信号契约 v1**（详见 `docs/integration.md`）
  - schema_version、generated_at、model、trading_date、valid_until
  - 每只股票：score / rank / quantile / action(BUY|HOLD|SELL) / confidence
- README.md（项目目的、与 quant-learn 关系、启动方式、已知坑、下一步）
- docs/integration.md（quant-qlib → quant-learn 桥接设计文档）

### 已知问题

1. **qlib 公开数据停在 2020-09-25**，不能直接用于"今天"的实盘信号。要更新到 2026 数据需自己写抓取/格式化流程（baostock + qlib_data dump_bin），下一阶段做。
2. **IC=None bug**（仅 user_pool 脚本）：
   - 原因：`D.features` 出来的 MultiIndex 顺序是 (instrument, datetime)，与 `pred` 的 (datetime, instrument) 不齐，导致 `pd.concat(join="inner")` 全空。
   - 主线 agent 已修，但因 PowerShell 管道 OOM 导致重跑没完成。
   - 不影响 demo IC（demo IC=0.0368 是 qlib `SigAnaRecord` 自己算的，落在 `mlruns/`）。
3. **子 agent 在 40 分钟硬上限 timeout**，CHANGELOG.md 未由子 agent 写入；本文件由主线补齐。
4. **MAX_PATH 限制**：venv 不能放在 `quant-qlib/.venv-qlib`，必须放短路径。

### 未实现（留作下一阶段）

- 桥接器代码（quant-qlib 写 signals.json → quant-learn 读消费），仅有设计文档。
- XGBoost / Linear / LSTM 模型对比。
- 用户股池的扩大（建议 50+ 只）。
- 数据更新到 2026-05。
- Workflow YAML 化（以便 `qrun` 一键复现）。
