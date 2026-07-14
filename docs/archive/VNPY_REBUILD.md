# vnpy-rebuild branch

## 目标
基于 vnpy 4.4 + xtquant + 国金 mini-QMT，重构为标准量化系统：
- 抛弃自写 sim/ broker/ scripts/ 散乱代码
- 完全按 vnpy 标准目录组织
- 跑通：行情订阅 → 策略 → 模拟下单 → 持仓查询 闭环

## 环境清单（已确认）
- vnpy 4.4.0 + vnpy_ctastrategy + vnpy_portfoliostrategy + vnpy_sqlite + vnpy_xt 1.4.6
- xtquant（国金原生版，从 D:\国金QMT交易端模拟\bin.x64\Lib\site-packages\xtquant 复制到 venv）
- 国金 QMT 模拟客户端：D:\国金QMT交易端模拟\
- mini-QMT 端口：58600（行情已连通）
- 账户：704121 / 970520 / 970525

## 重要：xtdata 端口修正
xtdata 默认连 58610（投研版），但国金 mini 监听 58600
代码里务必：xtdata.reconnect("localhost", 58600)

## 目录结构（按 vnpy 标准）
```
quant-learn/
├── vqlearn/                 ← 新代码全部放这（避免和旧 scripts 冲突）
│   ├── core/                引擎 + 数据层抽象
│   ├── gateways/            QMT mini gateway
│   ├── strategies/          CtaTemplate 策略
│   ├── apps/                选股/复盘/告警 应用
│   ├── notifiers/           通知层（企微/iwiki）
│   └── runners/             入口脚本
│
├── tests/                   单元测试
├── docs/                    文档
└── (legacy code in scripts/, sim/, broker/, ... 保留 master 分支)
```

## 持仓 + 观察池（来自 sim_live_mirror.db / portfolio_alert RULES）
**4 只持仓**：
- 600330.SH 天通股份 400股 cost=32.818
- 002256.SZ 兆新股份 700股 cost=5.246
- 002453.SZ 华软科技 300股 cost=6.467
- 603601.SH 再升科技 (qty?)

**22 只观察池**（绿电+半导体+其他）

## 待用户操作
- [ ] 在 mini-QMT 开「Python 接口连接」（XtQuantTrader.connect 才能成功）
