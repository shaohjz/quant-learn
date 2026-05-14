# A股量化回测系统

基于 Backtrader + AKShare 的 A 股量化回测框架，支持多策略对比分析。

## 目录结构

```
quant/
├── README.md              # 使用说明
├── backtest.py            # 回测主程序
├── run_backtest.sh        # 一键运行脚本
├── data/
│   ├── fetch_data.py      # 数据获取脚本
│   ├── 000967.csv         # 盈峰环境日线数据
│   └── 002256.csv         # 兆新股份日线数据
├── strategies/
│   ├── sma_cross.py       # 双均线交叉策略
│   ├── macd_strategy.py   # MACD策略
│   └── bollinger_strategy.py  # 布林带策略
└── output/
    ├── *.png              # 收益曲线图
    └── summary.csv        # 回测结果汇总
```

## 快速开始

### 一键运行（推荐）

```bash
cd /root/.openclaw/workspace/quant
bash run_backtest.sh
```

这会自动拉取数据、对盈峰环境和兆新股份分别跑三个策略、输出对比结果。

### 分步运行

#### 1. 拉取数据

```bash
# 拉取默认股票（盈峰环境 + 兆新股份，最近2年）
python3 data/fetch_data.py

# 拉取指定股票
python3 data/fetch_data.py 600519 20230101 20260513
```

#### 2. 运行回测

```bash
# 使用双均线策略回测盈峰环境
python3 backtest.py --stock 000967 --strategy sma_cross

# 使用MACD策略回测兆新股份
python3 backtest.py --stock 002256 --strategy macd_strategy

# 使用布林带策略，自定义初始资金
python3 backtest.py --stock 000967 --strategy bollinger_strategy --cash 200000
```

## 策略说明

### 1. 双均线策略 (sma_cross)
- **买入信号**: 5日均线上穿20日均线（金叉）
- **卖出信号**: 5日均线下穿20日均线（死叉）
- **风控**: 10% 止损

### 2. MACD策略 (macd_strategy)
- **买入信号**: MACD线上穿信号线（金叉）
- **卖出信号**: MACD线下穿信号线（死叉）
- **仓位管理**: 每次交易只使用 50% 可用资金

### 3. 布林带策略 (bollinger_strategy)
- **买入信号**: 收盘价触及或跌破布林带下轨
- **卖出信号**: 收盘价触及或突破布林带上轨
- **止损**: 价格跌破布林带中轨时平仓

## 费用模型

- 手续费: 0.1%（双边）
- 印花税: 0.05%（仅卖出）
- 最低手续费: 5元/笔
- 交易单位: 100股（1手）

## 评估指标

| 指标 | 说明 |
|------|------|
| 总收益率 | 期末市值 / 初始资金 - 1 |
| 年化收益率 | 按 252 个交易日年化 |
| 最大回撤 | 净值从峰值到谷值的最大跌幅 |
| 夏普比率 | 风险调整后收益（无风险利率 3%） |
| 交易次数 | 总开平仓次数 |
| 胜率 | 盈利交易 / 总完成交易 |

## 数据来源

- **AKShare**: `stock_zh_a_hist` 接口，前复权日线数据
- **备选**: BaoStock（当 AKShare 接口受限时自动降级）

## 依赖

```
backtrader>=1.9.78
akshare>=1.18
matplotlib>=3.5
pandas>=2.0
```

## 注意事项

1. AKShare 接口有调用频率限制，脚本内置 1 秒间隔
2. 数据默认为前复权（qfq），确保回测准确
3. matplotlib 使用 Agg 后端，无需 GUI 环境
4. 收益曲线图保存在 `output/` 目录
