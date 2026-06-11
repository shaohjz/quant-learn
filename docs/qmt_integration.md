# QMT 程序化交易接入指南

> 项目：quant-learn
> 目标：把 `broker/qmt_broker.py` 里那一堆 `NotImplementedError` 替换成真实的 xtquant 调用
> 状态：📚 学习文档（Phase C），代码补完在 Phase B

---

## 1. QMT 是啥？xtquant 又是啥？

| 概念 | 是什么 | 对开发者意味着什么 |
|---|---|---|
| **QMT 客户端** | 国金证券提供的桌面交易软件（行情 + 交易二合一），底层是迅投科技的 QMT 平台 | 必须**先开着这个 GUI**，下单/查询接口才能用 |
| **xtquant** | QMT 自带的 Python SDK，安装目录里有 `bin.x64/Lib/site-packages/xtquant` | 程序通过 xtquant 跟正在运行的 QMT 进程通信 |
| **userdata_mini** | QMT 客户端的会话/缓存目录 | xtquant 连接时必须传它的绝对路径，不然找不到 QMT 进程 |

**架构图（脑内模型）：**

```
你的策略代码 (Python)
       ↓ import xtquant
   xtquant SDK
       ↓ 本地 socket / 命名管道
   QMT 客户端 (必须运行中)
       ↓ 加密通道
   国金证券柜台
       ↓
   交易所
```

⚠️ **关键认知**：xtquant 不是直连券商的，它**只是 QMT 客户端的本地遥控器**。
QMT 没开 → 你的代码会一直 connect 失败。

---

## 2. xtquant 两条主线

xtquant 库分两块，**对应两个完全独立的模块**：

### 2.1 `xtquant.xtdata`：行情数据

```python
from xtquant import xtdata

# 订阅实时 tick
xtdata.subscribe_quote("000001.SZ", period="tick")

# 拿历史 K 线（日线/分钟线）
xtdata.get_market_data(
    field_list=["open", "high", "low", "close", "volume"],
    stock_list=["000001.SZ"],
    period="1d",
    start_time="20260101",
    end_time="20260516",
)

# 实时 tick 回调
def on_tick(data):
    print(data)

xtdata.subscribe_quote("000001.SZ", period="tick", callback=on_tick)
```

📌 **本项目目前不用 xtdata**：行情走 akshare/baostock 就够了，xtdata 是 Phase 4 才考虑的事。

### 2.2 `xtquant.xttrader`：交易接口（**就是你要补的那部分**）

```python
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount

# 1) 创建 trader 实例（必须传 userdata_mini 路径 + 唯一 session_id）
trader = XtQuantTrader(r"D:\国金QMT\userdata_mini", 123456)

# 2) 注册回调（成交/委托状态变化 由 QMT 主动推送，必须监听）
class MyCallback(XtQuantTraderCallback):
    def on_stock_order(self, order):       # 委托状态变化
        ...
    def on_stock_trade(self, trade):       # 成交回报
        ...
    def on_order_error(self, err):         # 委托失败
        ...
    def on_disconnected(self):             # 断线
        ...

trader.register_callback(MyCallback())

# 3) 启动 + 连接
trader.start()
ret = trader.connect()                # 0 表示成功
assert ret == 0

# 4) 订阅指定账户（必须订阅完才能下单/查询）
account = StockAccount("90072426")     # 资金账号
sub = trader.subscribe(account)
assert sub == 0

# 5) 下单
order_id = trader.order_stock(
    account=account,
    stock_code="000001.SZ",            # 注意带交易所后缀
    order_type=xtconstant.STOCK_BUY,   # 买/卖常量
    order_volume=100,                  # 必须是 100 的整数倍
    price_type=xtconstant.FIX_PRICE,   # 限价单
    price=10.50,
    strategy_name="quant-learn",
    order_remark="test buy",
)

# 6) 查询
positions = trader.query_stock_positions(account)
asset = trader.query_stock_asset(account)
orders = trader.query_stock_orders(account)
trades = trader.query_stock_trades(account)

# 7) 撤单
trader.cancel_order_stock(account, order_id)

# 8) 收尾
trader.stop()
```

---

## 3. 关键常量（xtquant.xtconstant）

| 常量 | 值（参考） | 含义 |
|---|---|---|
| `STOCK_BUY` | 23 | 股票买入 |
| `STOCK_SELL` | 24 | 股票卖出 |
| `FIX_PRICE` | 11 | 限价单 |
| `MARKET_SH_CONVERT_5_CANCEL` | 42 | 沪市最优 5 档剩余撤销（市价单） |
| `MARKET_SZ_CONVERT_5_CANCEL` | 47 | 深市最优 5 档剩余撤销（市价单） |

**坑提示**：股票代码必须带交易所后缀！
- 上海主板/科创：`600000.SH` / `688981.SH`
- 深圳主板/创业：`000001.SZ` / `300750.SZ`
- 北交所：`830799.BJ`

---

## 4. 同步 vs 异步：本项目选谁？

xtquant 的下单 API 有两套：

| API | 行为 | 适用场景 |
|---|---|---|
| `order_stock()` | **同步**：返回委托号，但成交结果走回调 | 适合策略里直接调 |
| `order_stock_async()` | 异步：立即返回，全部走回调 | 高频/批量场景 |

本项目用 `order_stock()` 即可，但**成交回报必须靠回调**（因为下单 ≠ 成交）。

### 设计建议（对接到 IBroker.buy 的逻辑）

```
buy() 被调用
  → trader.order_stock()  拿到 order_id
  → 立刻返回 OrderResult(success=True, order_id=xxx)，但这只是"已委托"
  → 真正成交由 on_stock_trade 回调写入 sim_trades 表
  → 上层策略不需要等待成交，下一根 K 线再决策即可
```

⚠️ **本项目骨架的 buy/sell 是"立即成交"模型**，对接 QMT 后需要语义对齐：
- 方案 A（推荐）：buy 返回"已委托"，成交由回调异步落库
- 方案 B（懒人）：下单后用 `time.sleep(1) + query_stock_trades` 同步轮询（不优雅但简单）

---

## 5. 安装 xtquant 的两种方式

QMT 客户端装好后，xtquant 在它的安装目录里：

```
D:\国金QMT\
  ├─ bin.x64\
  │   └─ Lib\
  │       └─ site-packages\
  │           └─ xtquant\          ← 就是这个文件夹
  ├─ userdata_mini\                ← 这个路径要填到 config.local.yaml
  └─ ...
```

### 方式 1：复制到当前 Python 环境（最快）
```powershell
# 把 xtquant 整个文件夹复制到你的 site-packages
Copy-Item -Recurse "D:\国金QMT\bin.x64\Lib\site-packages\xtquant" `
  "<你的 venv 路径>\Lib\site-packages\xtquant"
```

### 方式 2：用 PYTHONPATH 指向（推荐，便于升级）
```powershell
$env:PYTHONPATH = "D:\国金QMT\bin.x64\Lib\site-packages;$env:PYTHONPATH"
python -c "from xtquant import xttrader; print('ok')"
```

🚨 **注意 Python 版本必须匹配**：xtquant 编译版本一般是 **Python 3.7 / 3.10 / 3.11**，
QMT 安装目录会有提示。装错版本的 Python 会报 `ImportError: DLL load failed`。

---

## 6. Phase B 写 qmt_broker.py 的对照表

| IBroker 方法 | 对应 xtquant 调用 | 备注 |
|---|---|---|
| `connect()` | `XtQuantTrader(...).start()` + `.connect()` + `.subscribe(account)` | 当前骨架已写好，能跑 |
| `disconnect()` | `trader.stop()` | 已写好 |
| `buy()` | `trader.order_stock(account, code, STOCK_BUY, qty, FIX_PRICE, price)` | **要补**：返回 OrderResult，成交走回调 |
| `sell()` | `trader.order_stock(account, code, STOCK_SELL, qty, FIX_PRICE, price)` | **要补**，同上 |
| `cancel()` | `trader.cancel_order_stock(account, order_id)` | **要补** |
| `get_account()` | `trader.query_stock_asset(account)` | **要补**：返回 Account dataclass |
| `get_positions()` | `trader.query_stock_positions(account)` | **要补**：返回 Position[] |
| `update_prices()` | 不调 xtquant，可选地同步到 sim_positions | 可选 |
| `daily_settle()` | `query_stock_asset()` + 写 nav 表 | **要补** |

回调里要做的事：

| 回调 | 处理 |
|---|---|
| `on_stock_trade` | 写 `sim_trades` 表（broker='qmt'），保持账本一致 |
| `on_stock_order` | 可选：日志记录委托状态 |
| `on_order_error` | 必须：日志告警，可考虑发企微 |
| `on_disconnected` | 必须：标记 `_connected=False`，触发重连 |

---

## 7. 一定要避开的坑（先写在这，等真上的时候回来看）

1. ❌ **没开 QMT 客户端就跑代码** → connect 永远失败
2. ❌ **session_id 在多个进程间冲突** → 后启的会被踢
3. ❌ **股票代码不带 .SH/.SZ** → 报无效合约
4. ❌ **委托数量不是 100 整数倍** → 直接拒单（除非是创业板/科创板的零股卖出）
5. ❌ **价格小数位超过证券规则**（A 股 2 位）→ 拒单
6. ❌ **集合竞价时段下市价单** → 部分券商会拒
7. ❌ **没 subscribe 就下单** → 下单失败
8. ❌ **回调里写阻塞代码** → 卡住整个交易循环（落库要异步队列）
9. ❌ **测试账号当生产用** → 数据有偏差，且测试环境不模拟所有交易所规则
10. ❌ **断线没重连** → on_disconnected 必须处理

---

## 8. 测试单跑通流程（等 Phase B 写完后用）

```bash
# 0. 启动 QMT 客户端，登录测试账号 90072426
# 1. 切换 broker mode 到 live
#    config.local.yaml:
#      broker:
#        mode: live
#        qmt_path: "D:\\国金QMT\\userdata_mini"
#        account_id: "90072426"

# 2. 跑最小测试单（写在 scripts/test_qmt_min_order.py）
python scripts/test_qmt_min_order.py --code 000001.SZ --qty 100 --price 10.50

# 期望：
# - QMT 客户端委托列表里出现 1 条
# - on_stock_order / on_stock_trade 回调被触发
# - sim_trades 表多 1 条 broker='qmt' 的记录
# - 数据库 sim_positions 同步更新
```

---

## 9. 参考资料（按可信度排序）

1. **QMT 客户端安装目录的 doc/ 文件夹** ← 最权威，xtquant API 完整 PDF
2. **迅投官方 wiki**：https://dict.thinktrader.net/nativeApi/xtquant.html
3. **国金证券 QMT 服务群**（开通的时候销售应该给了二维码）
4. **GitHub `xtquant` 相关 demo**（搜 `XtQuantTrader` 关键字，警惕来路不明的 fork）

---

## 10. 本文档维护

每次实际碰到新坑，往 §7 加一条；每次接通新 API，更新 §6 状态。
完成 Phase B 后，删除 `qmt_broker.py` 里所有 `NotImplementedError`，并把本文档 §6 各行打 ✅。
