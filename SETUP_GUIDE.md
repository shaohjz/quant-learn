# 量化模拟盘项目 — 部署与运行指南

## Git 地址

```
git@git.woa.com:jizhouhu/quant-learn.git
```

Web 浏览：https://git.woa.com/jizhouhu/quant-learn

---

## 1. 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows（推荐）或 Linux |
| Python | 3.10+ |
| Node.js | 18+（仅 OpenClaw 环境需要） |
| 数据库 | SQLite（内置，无需单独安装） |

---

## 2. 克隆代码

```bash
git clone git@git.woa.com:jizhouhu/quant-learn.git
cd quant-learn
```

> 如果遇到权限问题，先配置工蜂 SSH Key：https://git.woa.com/-/profile/keys

---

## 3. Python 环境配置

```bash
# 创建虚拟环境
python -m venv venv

# 激活（Windows）
venv\Scripts\activate

# 激活（Linux/Mac）
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

> 如果 `requirements.txt` 不存在，手动安装核心依赖：
> ```bash
> pip install pandas numpy requests flask apscheduler
> ```

---

## 4. 项目结构

```
quant-learn/
├── config.yaml              # 主配置文件
├── config_auto.yaml         # 自动生成的配置
├── run_daily.py             # 每日运行入口
├── run_daily_improved.py    # 改进版每日运行
├── scripts/                 # 核心脚本
│   ├── sim_executor.py      # 模拟盘执行器
│   ├── sim_executor_v2.py   # 模拟盘V2
│   ├── daily_review.py      # 每日复盘
│   ├── gen_daily_report.py  # 生成日报
│   ├── auto_trader_v3.py    # 自动交易引擎
│   ├── intraday_scanner.py  # 盘中扫描
│   ├── portfolio_alert.py   # 持仓预警
│   ├── pm_cli.py            # PM命令行工具
│   └── wecom_webhook_push.py # 企微推送
├── data/                    # 行情数据（CSV）
├── vqlearn/                 # 核心库
├── tests/                   # 测试
└── web/                     # Web界面
```

---

## 5. 配置说明

### 5.1 基础配置

编辑 `config.yaml`，主要配置项：

```yaml
# 模拟盘
simulation:
  initial_capital: 300000  # 初始资金
  max_positions: 5         # 最大持仓数
  position_size_pct: 0.25  # 单只仓位比例

# 数据源
data_source:
  type: sina_curl  # 数据源类型

# 推送通知
notifier:
  wecom_webhook: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
```

### 5.2 企微 Webhook 配置

在 `config.yaml` 中配置：

```yaml
notifier:
  wecom_webhook: "你的Webhook地址"
```

获取方式：企微群 → 群设置 → 群机器人 → 添加

---

## 6. 运行方式

### 6.1 每日复盘

```bash
# 生成当日复盘报告
python scripts/daily_review.py

# 详细版日报
python scripts/gen_daily_report.py
```

### 6.2 模拟盘交易

```bash
# 运行模拟盘执行器
python scripts/sim_executor.py

# 改进版
python scripts/sim_executor_v2.py
```

### 6.3 盘中扫描

```bash
python scripts/intraday_scanner.py
```

### 6.4 持仓预警

```bash
python scripts/portfolio_alert.py
```

### 6.5 PM 命令行工具

```bash
# 查看持仓
python scripts/pm_cli.py positions

# 查看当日信号
python scripts/pm_cli.py signals

# 查看账户状态
python scripts/pm_cli.py status
```

### 6.6 Web 界面

```bash
python web/app.py
# 访问 http://localhost:5000
```

---

## 7. 在 OpenClaw 环境中运行

如果你在 OpenClaw（内网版）环境中运行，项目已预置在：
```
C:\Users\Administrator\.openclaw\workspace\quant-learn
```

自动运行的 Cron 任务会在每日收盘后执行复盘，企微推送结果。

---

## 8. 常见问题

### Q: 行情数据如何更新？
A: 脚本会自动从数据源拉取最新行情。如需手动更新：
```bash
python scripts/refetch_latest_data.py
```

### Q: 数据库在哪？
A: 模拟盘数据库在 `data/pm.db`（已加入 .gitignore，不会提交到 Git）

### Q: 日志在哪看？
A: 运行日志在 `logs/` 目录，执行日志在 `output/*.log`

### Q: 数据源连不上？
A: 检查网络环境。内网环境可能需要配置代理或使用 baostock 数据源。

---

## 9. 注意事项

1. **这是模拟盘**，所有交易均为模拟，不涉及真实资金
2. 行情数据延迟约 1-5 分钟，不适用于高频交易
3. 首次运行需要先拉取历史行情数据
4. 建议每日收盘后运行复盘脚本查看当日表现
