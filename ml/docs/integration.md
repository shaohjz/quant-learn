# 集成设计：quant-qlib → quant-learn

> **状态：设计中（v0.1），未实现。**
> 本文档定义未来 qlib 模型信号如何接入 `quant-learn/scripts/portfolio_alert.py`。
> 目前 quant-learn 不读取任何来自 qlib 的文件，行为不变。

---

## 1. 目标

让 qlib 训出的"AI 视角"——对**用户 10 只股票每日的 score**——参与 quant-learn 的盘中决策：

- 当 AI 持续看空 + 价格也跌破预设止损 → 提示更紧迫
- 当 AI 看多 + 价格回落到 buy_zone → 提示"双重买入信号"
- 当 AI 评分突变 → 单独发出一条"AI 信号变更"提醒（不依赖价格阈值）

quant-learn 现有的 `RULES`（价格阈值表）保留不动；qlib 信号是**叠加层**。

---

## 2. 总体数据流

```
[ qlib backtest / inference job ]   每天盘后跑一次
            │
            ▼
   model_predict(stock_pool, today) → DataFrame: code, score, rank
            │
            ▼
[ src/signal_exporter.py ]   分位数映射 → BUY / HOLD / SELL
            │
            ▼
   output/signals.json  (原子写：先写 .tmp 再 rename)
            │
   [ 跨项目读取 ─ 路径硬编码或环境变量 ]
            │
            ▼
[ quant-learn/scripts/portfolio_alert.py ]
   - 启动时尝试 load_qlib_signals()
   - 把 BUY/SELL 信号合入 RULES，作为额外行动等级 'ai_buy' / 'ai_sell'
            │
            ▼
   触发 → webhook 推送（已有逻辑）
```

---

## 3. score → action 映射

qlib 的 LightGBM 输出 `score`（连续值，越高越看好）。
对当天股池里每只股票：

| 条件                                | action  |
|-------------------------------------|---------|
| `score` 在股池中分位 ≥ 80%（top 20%） | `BUY`   |
| `score` 在股池中分位 ≤ 20%（bottom 20%）| `SELL`  |
| 其它                                 | `HOLD`  |

阈值在 `config.yaml` → `bridge.thresholds.buy_quantile / sell_quantile` 中可调。

10 只股票的小池里"分位"波动可能很剧烈，因此还要加置信度过滤：

- 当日股池 score 标准差 < 阈值 σ_min → 全部回退为 `HOLD`（模型没区分度）
- 模型给出的 IC、Rank IC 历史窗口低于 0.02 → 退化为 `HOLD`（信号不可信）

---

## 4. signals.json 结构（契约）

```json
{
  "schema_version": "1",
  "generated_at": "2026-05-19T17:42:00+08:00",
  "model": "lightgbm-alpha158-userpool-v1",
  "trading_date": "2026-05-19",
  "valid_until": "2026-05-20T15:00:00+08:00",
  "metadata": {
    "ic": 0.043,
    "rank_ic": 0.061,
    "stock_pool_size": 10
  },
  "signals": [
    {
      "code": "600330",
      "qlib_code": "SH600330",
      "name": "天通股份",
      "score": 0.0123,
      "rank": 3,
      "quantile": 0.70,
      "action": "HOLD",
      "confidence": 0.62
    },
    {
      "code": "002156",
      "qlib_code": "SZ002156",
      "name": "通富微电",
      "score": 0.0418,
      "rank": 1,
      "quantile": 1.00,
      "action": "BUY",
      "confidence": 0.81
    }
  ]
}
```

**契约要点**

- `code` 用 6 位数字（与 quant-learn `RULES` 一致），`qlib_code` 保留 qlib 风格做调试。
- `valid_until`：超过该时刻的信号视为失效，consumer 必须忽略。
- `schema_version` bump 时通知双方。

---

## 5. quant-learn 端的消费方式（**待实现，不在本次提交中**）

未来在 `quant-learn/scripts/portfolio_alert.py` 增加一个 **加载函数**（不动现有 RULES，只追加）：

```python
QLIB_SIGNALS = ROOT.parent / "quant-qlib" / "output" / "signals.json"

def load_qlib_signals():
    """读取并校验 qlib 信号；失败时返回 []，不影响主流程。"""
    if not QLIB_SIGNALS.exists():
        return []
    try:
        data = json.loads(QLIB_SIGNALS.read_text(encoding="utf-8"))
        # 1) schema_version 校验
        if data.get("schema_version") != "1":
            return []
        # 2) valid_until 校验
        if datetime.fromisoformat(data["valid_until"]) < datetime.now(...):
            return []
        # 3) 转换为伪 RULES（dir 用特殊值 'ai'）
        out = []
        for s in data["signals"]:
            if s["action"] == "BUY":
                out.append({
                    "code": s["code"], "name": s["name"],
                    "level": "ai_buy",
                    "trigger": None, "dir": "ai",
                    "message": f"🤖 AI 看多 #{s['rank']} 置信{s['confidence']:.0%}（score={s['score']:.4f}）",
                })
            elif s["action"] == "SELL":
                out.append({...})
        return out
    except Exception as e:
        logger.warning(f"qlib signals 读取失败: {e}")
        return []
```

主循环里在 `for rule in RULES + load_qlib_signals():` 即可。

> **特别注意**
> - `dir = 'ai'` 不参与价格比较；触发条件改成"今日首次出现 + 当前在交易时段"。
> - 每天盘前 9:25 触发一次 AI 信号；若 score 当天有跳动可重跑 qlib 推理后再触发。
> - 触发后写入 `alert_state.json` 的 key 用 `ai_buy:002156:20260519`，复用既有去重逻辑。

---

## 6. 失败兜底

- qlib 预测脚本崩了 → 不写 signals.json → quant-learn 读不到 → 行为退化到原有 RULES。
- signals.json 格式坏 → schema 检查失败 → 同样静默忽略。
- **关键不变量**：quant-learn 的安全性不能依赖 quant-qlib 是否健康。

---

## 7. 路径与协议总结

| 项 | 值 |
| --- | --- |
| 信号写入路径 | `C:\Users\Administrator\.openclaw\workspace\quant-qlib\output\signals.json` |
| 协议 | JSON v1（见 §4） |
| 写入频率 | 每交易日一次（盘后 17:00 左右）|
| 失效时间 | 下一交易日收盘 |
| 跨进程同步 | 原子重命名（写 `.tmp` 再 `os.replace`）|
| 反向通信 | **无**——quant-learn 不回写 |

---

## 8. 未决事项

- [ ] 是否要在 signals.json 里附带"建议仓位百分比"（凯利公式 / 等权）
- [ ] 是否要支持多模型集成（LightGBM + Linear + ALSTM 的投票）
- [ ] 触发"AI 信号变更"的去重 key 设计（避免每日同一信号重复推送）
- [ ] 当 IC 很低时是否仍生成信号但只标 `confidence: low`，由 quant-learn 自行决定是否过滤
