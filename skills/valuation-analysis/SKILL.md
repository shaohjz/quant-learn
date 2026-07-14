---
name: valuation-analysis
description: A股个股估值分析工具 — 获取PE(TTM)/PB/估值分位/行业对比，判断股票估值高低，辅助买入决策
origin: custom
version: 1.0.0
---

# A股估值分析工具 V1.0.0

## 概述

本 skill 提供 A 股个股的估值分析能力，基于 a-stock-data 的数据接口，获取 PE(TTM)、PB、行业估值分位等指标，判断股票估值是否合理。

**核心用途：**
1. **买入前估值过滤** — 技术信号触发时，先检查估值是否合理
2. **每日扫描过滤** — watchlist 只保留低估值股票
3. **持仓估值监控** — 定期检查持仓股估值变化

## 数据源

| 数据 | 来源 | 接口 |
|------|------|------|
| PE(TTM) / PB | 腾讯财经 API | 腾讯个股行情（含 pe_ttm, pb） |
| 行业估值分位 | 东财 push2 | 个股信息（含行业、总市值） |
| 财务数据 | mootdx finance | 季报快照（EPS、ROE、净利润） |
| 行业对比 | 东财行业板块 | 行业涨跌/排名 |
| 历史估值 | 百度 K线 | 带 MA5/10/20 的历史价格 |

## 分析流程

### Step 1: 获取个股估值数据

使用腾讯财经 API 获取实时 PE(TTM) 和 PB：

```python
import requests
import json

def get_tencent_quote(stock_code):
    """
    获取腾讯财经行情（含 PE/PB）
    stock_code: 如 '600519'（6位代码，不含前缀）
    """
    # 腾讯接口：sh=上海，sz=深圳，bj=北交所
    prefix = {'6': 'sh', '0': 'sz', '3': 'sz', '8': 'bj', '4': 'bj'}
    market = prefix.get(stock_code[0], 'sh')
    url = f'https://qt.gtimg.cn/q={market}{stock_code}'
    resp = requests.get(url, timeout=10)
    # 返回格式：v_sh600519="1~贵州茅台~...~pe_ttm~pb~..."
    parts = resp.text.split('~')
    # 常用字段索引（腾讯格式固定）
    fields = {
        'name': 1,        # 名称
        'price': 3,       # 当前价
        'pe_ttm': 39,     # 市盈率(动态)
        'amplitude': 43,  # 振幅
        'pb': 46,         # 市净率
        'market_cap': 45, # 总市值(万)
        'circulating_cap': 44, # 流通市值(万)
        'high': 33,       # 最高
        'low': 34,        # 最低
        'open': 15,       # 开盘
        'volume': 36,     # 成交量(手)
        'amount': 37,     # 成交额(万)
    }
    result = {}
    for key, idx in fields.items():
        if idx < len(parts):
            result[key] = parts[idx]
    return result

# 使用示例
quote = get_tencent_quote('600519')
print(f"{quote.get('name')} | PE: {quote.get('pe_ttm')} | PB: {quote.get('pb')} | 市值: {quote.get('market_cap')}万")
```

### Step 2: 估值合理性判断

```python
def check_valuation_reasonable(pe_ttm, pb, industry_avg_pe=None):
    """
    判断估值是否合理
    返回: (is_reasonable, reason)
    """
    reasons = []
    
    # 1. PE 检查
    try:
        pe = float(pe_ttm)
        if pe <= 0:
            reasons.append(f"PE={pe}（亏损/负值，需结合PB判断）")
            return True, '; '.join(reasons)  # 亏损股用PB判断
        elif pe > 100:
            reasons.append(f"PE={pe:.1f} > 100（估值过高）")
            return False, '; '.join(reasons)
        elif pe > 50:
            reasons.append(f"PE={pe:.1f}（偏高，需确认成长性）")
        elif pe < 15:
            reasons.append(f"PE={pe:.1f}（偏低，可能低估）")
        else:
            reasons.append(f"PE={pe:.1f}（合理区间）")
    except (ValueError, TypeError):
        reasons.append("PE数据异常")
    
    # 2. PB 检查
    try:
        pb_val = float(pb)
        if pb_val > 10:
            reasons.append(f"PB={pb_val:.1f} > 10（极高，轻资产/成长股特征）")
        elif pb_val > 5:
            reasons.append(f"PB={pb_val:.1f}（偏高）")
        elif pb_val < 1:
            reasons.append(f"PB={pb_val:.1f} < 1（破净，需确认资产质量）")
        else:
            reasons.append(f"PB={pb_val:.1f}（合理区间）")
    except (ValueError, TypeError):
        reasons.append("PB数据异常")
    
    # 3. 行业对比（如果有行业均值）
    if industry_avg_pe:
        try:
            pe_ratio = pe / industry_avg_pe
            if pe_ratio > 1.5:
                reasons.append(f"PE/行业均值={pe_ratio:.1f}x（高于行业50%以上）")
                return False, '; '.join(reasons)
            elif pe_ratio < 0.5:
                reasons.append(f"PE/行业均值={pe_ratio:.1f}x（显著低于行业均值）")
        except:
            pass
    
    return True, '; '.join(reasons)
```

### Step 3: 批量估值扫描

对 watchlist 或观察池批量获取估值数据：

```python
def batch_valuation(stock_codes):
    """
    批量获取估值数据
    stock_codes: ['600519', '000858', '002475']
    返回: [{code, name, pe_ttm, pb, market_cap, valuation_level}, ...]
    """
    results = []
    for code in stock_codes:
        quote = get_tencent_quote(code)
        if not quote.get('pe_ttm'):
            continue
        is_ok, reason = check_valuation_reasonable(
            quote.get('pe_ttm'), 
            quote.get('pb')
        )
        results.append({
            'code': code,
            'name': quote.get('name'),
            'pe_ttm': quote.get('pe_ttm'),
            'pb': quote.get('pb'),
            'market_cap': quote.get('market_cap'),
            'valuation_level': '合理' if is_ok else '偏高',
            'reason': reason
        })
    return results
```

### Step 4: 估值分位计算（历史对比）

结合百度 K 线数据计算历史估值分位：

```python
def get_historical_valuation_percentile(stock_code, days=252):
    """
    计算历史估值分位（过去252个交易日）
    返回: {current_pe, pe_percentile, current_pb, pb_percentile}
    """
    # 使用 a-stock-data §2.3 百度K线获取历史数据
    # 从历史数据中提取每日PE/PB（腾讯接口有历史快照）
    # 计算当前值在历史区间中的分位
    pass  # 具体实现参考 a-stock-data skill
```

## 估值过滤规则（建议）

| 条件 | 操作 |
|------|------|
| PE < 0（亏损） | 跳过，除非有强反转信号 |
| PE > 100 | 过滤，不买入 |
| PE > 行业均值 × 1.5 | 过滤，估值偏高 |
| PB > 10（非科技股） | 过滤，估值极高 |
| PB < 1（破净） | 标记为"破净"，需额外分析 |
| PE 15-40 + PB 1-5 | 合理区间，正常交易 |

## 估值信号写入

估值分析结果写入 `strategy_shadow_signals` 表：

```python
def write_valuation_signal(stock_code, pe_ttm, pb, is_reasonable, reason):
    """
    将估值分析结果写入信号表
    """
    import sqlite3
    from datetime import datetime
    
    conn = sqlite3.connect('data/sim_live_mirror.db')
    c = conn.cursor()
    
    signal = 'BUY' if is_reasonable else 'HOLD'
    confidence = 0.8 if is_reasonable else 0.3
    
    c.execute('''
        INSERT INTO strategy_shadow_signals 
        (stock_code, strategy_id, signal_action, confidence, signal_reason, signal_date, created_at)
        VALUES (?, 'valuation_filter', ?, ?, ?, ?, ?)
    ''', (
        stock_code,
        signal,
        confidence,
        f"估值分析: {reason}",
        datetime.now().strftime('%Y-%m-%d'),
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ))
    conn.commit()
    conn.close()
```

## 与现有系统集成

### 买入信号流程（建议修改 sim_executor.py）

```
技术信号触发（trend_break_buy / buy_zone / buy_strong）
    ↓
查询 valuation_filter 信号
    ↓
估值合理？ → 是 → 正常执行买入
    ↓
    否 → 跳过，记录原因
```

### watchlist 生成流程（建议修改 generate_next_watchlist.py）

```
从信号表获取候选股票
    ↓
批量获取估值数据
    ↓
过滤掉估值过高的股票
    ↓
生成最终 watchlist
```

## 依赖

- Python 3.8+
- requests
- a-stock-data skill（可选，用于更详细的财务数据）
- sqlite3（内置）

## 项目路径

```
C:\Users\Administrator\.openclaw\workspace\quant-learn
```

- 模拟盘 DB: `data/sim_live_mirror.db`
- PM DB: `data/pm.db`
- 信号脚本: `skills/a-stock-data-signals/`
