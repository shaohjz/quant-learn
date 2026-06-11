# 观察列表分层与盘中异动扫描设计方案

**版本**: 1.0  
**日期**: 2026-05-25  
**作者**: Subagent (quant-optimization-agent)

---

## 1. 问题诊断

### 1.1 现状
- **观察列表单一化**：`config.yaml` 中 `watchlist` 不区分来源，手动添加和系统推荐混在一起
- **盘中被动监控**：只在盘前 8:30 扫一次全市场（`morning_scanner.py`），盘中只盯固定列表
- **缺乏淘汰机制**：观察池只增不减，容易膨胀
- **缺少盘中异动捕获**：A股 T+1 制度下，盘中异动是重要买点，但现有架构无法捕获

### 1.2 用户需求
1. **观察列表分层**：
   - `user_manual`：用户手动指定（永久，除非用户明确删除）
   - `auto_discovered`：系统自动发现（有生命周期，自动淘汰）
   
2. **盘中全市场扫描**：
   - 覆盖范围：沪深300 + 中证500（约 800 只）
   - 扫描频率：每 30 分钟一次（9:30/10:00/10:30/11:00/13:30/14:00/14:30）
   - 触发条件：量价突破、涨停回落、跌破反弹等异动
   
3. **自动淘汰规则**：
   - 系统添加的票若 N 天无触发 → 移除
   - 趋势破位（跌破 MA20-1.5ATR）→ 移除
   - 用户手动添加的不自动删

---

## 2. 架构设计

### 2.1 观察列表分层结构

#### 2.1.1 config.yaml 新结构

```yaml
# ========== 观察池（分层管理）==========
watchlist:
  # ===== 用户手动指定（永久） =====
  user_manual:
    "002156":
      name: 通富微电
      enabled: true
      source: 玄鉴录
      added_at: 2026-05-19
      added_reason: 玄鉴录推荐量化首选
      tags: [半导体, 封装测试]
      rules:
        buy_zone:   { trigger: 60.04, dir: below, msg: "💰 通富微电跌至 60.04！接近 MA10(60.04)，试探建仓" }
        buy_strong: { trigger: 56.04, dir: below, msg: "💰💰 通富微电跌至 56.04！回踩 MA20(56.04)，优质建仓区" }
    
    "002290":
      name: 禾盛新材
      enabled: true
      source: 用户指定
      added_at: 2026-05-25
      added_reason: 用户观察
      tags: [新材料, 薄膜]
      rules:
        buy_zone:    { trigger: 95.58, dir: below, msg: "💰 禾盛新材跌至 95.58！接近 MA10" }
        trend_break: { trigger: 77.38, dir: below, msg: "⚠️ 禾盛新材破 77.38！趋势反转" }

  # ===== 系统自动发现（有生命周期） =====
  auto_discovered:
    "600519":
      name: 贵州茅台
      enabled: true
      source: intraday_scanner
      added_at: 2026-05-25
      added_by: "盘中异动扫描"
      added_reason: "盘中放量突破 MA20，量比 2.3"
      discovery_score: 85
      last_alert_at: 2026-05-25  # 最后一次触发告警的日期
      alert_count: 2             # 累计触发次数
      max_inactive_days: 7       # N 天无触发则淘汰
      tags: [白酒, 消费]
      rules:
        buy_zone:    { trigger: 1780.00, dir: below, msg: "💰 茅台回踩 MA10" }
        trend_break: { trigger: 1650.00, dir: below, msg: "⚠️ 茅台破趋势线" }
```

#### 2.1.2 数据库扩展

在 `sim_live_mirror.db` 新增 `watchlist_history` 表：

```sql
CREATE TABLE IF NOT EXISTS watchlist_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    category TEXT NOT NULL,  -- 'user_manual' | 'auto_discovered'
    added_at DATE NOT NULL,
    added_by TEXT,           -- 'user' | 'intraday_scanner' | 'morning_scanner'
    added_reason TEXT,
    discovery_score REAL,    -- 评分（仅 auto_discovered）
    last_alert_at DATE,      -- 最后触发日期
    alert_count INTEGER DEFAULT 0,
    removed_at DATE,         -- 移除日期（NULL = 未移除）
    removed_reason TEXT,     -- 移除原因（淘汰/用户删除）
    UNIQUE(code, category, added_at)
);

CREATE INDEX idx_watchlist_code ON watchlist_history(code);
CREATE INDEX idx_watchlist_removed ON watchlist_history(removed_at);
```

### 2.2 盘中异动扫描方案

#### 2.2.1 扫描器：scripts/intraday_scanner.py

**功能**：
- 盘中每 30 分钟扫描沪深300 + 中证500（约 800 只）
- 识别异动信号（量价突破/涨停回落/跌破反弹）
- 自动加入 `auto_discovered` 观察池
- 推送企微通知

**触发条件**（按优先级）：

1. **量价突破** (score 80-95)：
   - 当前价 > MA20
   - 量比 ≥ 1.5
   - 今日涨幅 1%-5%
   - 接近 20 日新高（距离 < 3%）

2. **涨停回落** (score 70-80)：
   - 早盘涨停（涨幅 ≥ 9.5%）
   - 当前回落至 5%-8% 区间
   - 量能持续放大

3. **超跌反弹** (score 60-75)：
   - 近 5 日跌幅 > 10%
   - 今日放量反弹（涨幅 3%-6%，量比 ≥ 2.0）
   - 未跌破 MA60

**风险过滤**（直接 PASS）：
- ST 股票
- 价格 > 500 或 < 2
- 成交额 < 1 亿
- 涨幅 > 7%（追高风险）
- 跌幅 > 7%（恐慌盘）

**输出**：
- 推送到企微：`🔍 盘中异动 (10:00) | 新增观察 3 只`
- 自动更新 `config.yaml` 的 `watchlist.auto_discovered`
- 记录到 `watchlist_history` 表

#### 2.2.2 扫描频率与时间窗口

```
交易日计划：
  9:30  首次扫描（开盘 30 分钟后，过滤开盘波动）
  10:00 第二次
  10:30 第三次
  11:00 尾盘（上午）
  13:30 开盘（下午）
  14:00 第五次
  14:30 尾盘（全天）
```

**Windows 计划任务**（使用 schtasks）：

```powershell
schtasks /create /tn "QuantLearn_IntradayScanner" /tr "C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts\intraday_scanner_runner.bat" /sc DAILY /st 09:30 /mo 1 /ru SYSTEM /rl HIGHEST
```

每次运行检查时间窗口，只在交易时段执行。

### 2.3 自动淘汰规则

#### 2.3.1 淘汰触发条件（仅针对 `auto_discovered`）

1. **无触发淘汰**：
   - 加入后 N 天（默认 7 天）未触发任何阈值
   - 操作：从 `config.yaml` 移除，`watchlist_history.removed_at` 记录时间
   - 原因：`"inactive_N_days"`

2. **趋势破位淘汰**：
   - 触发 `trend_break` 规则（跌破 MA20-1.5ATR）
   - 操作：立即从观察池移除
   - 原因：`"trend_broken"`

3. **评分衰减淘汰**：
   - 加入时 discovery_score < 60
   - 且 3 天内无触发
   - 原因：`"low_score_inactive"`

#### 2.3.2 淘汰执行器：scripts/cleanup_watchlist.py

- 每日盘前 8:00 运行（在 morning_scanner 之前）
- 检查 `auto_discovered` 中的所有股票
- 执行淘汰逻辑
- 更新 `config.yaml` 和 `watchlist_history`
- 推送淘汰报告到企微

```yaml
# Windows 计划任务
schtasks /create /tn "QuantLearn_CleanupWatchlist" /tr "C:\...\scripts\cleanup_watchlist_runner.bat" /sc DAILY /st 08:00
```

---

## 3. 数据流图

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户交互层                                 │
├─────────────────────────────────────────────────────────────────┤
│  用户手动添加 → config.yaml (watchlist.user_manual)              │
│  用户删除     → 修改 config.yaml + 记录到 watchlist_history      │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│                      系统自动层                                   │
├─────────────────────────────────────────────────────────────────┤
│  morning_scanner.py (8:30 盘前)                                 │
│    ↓ 全市场扫描 → Top 10 候选                                    │
│    ↓ AI 评估（可选）→ 自动加入 auto_discovered                   │
│                                                                  │
│  intraday_scanner.py (9:30/10:00/.../14:30 盘中)                │
│    ↓ 异动扫描（量价突破/涨停回落/超跌反弹）                         │
│    ↓ 自动加入 config.yaml (watchlist.auto_discovered)           │
│    ↓ 推送企微通知                                                 │
│                                                                  │
│  cleanup_watchlist.py (8:00 每日)                               │
│    ↓ 检查 auto_discovered 淘汰条件                               │
│    ↓ 移除过期/破位股票                                            │
│    ↓ 更新 config.yaml + watchlist_history                       │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│                      监控告警层                                   │
├─────────────────────────────────────────────────────────────────┤
│  portfolio_alert.py (每 10 分钟)                                 │
│    ↓ 加载 real_portfolio_rules (持仓股)                         │
│    ↓ 加载 watchlist.user_manual + watchlist.auto_discovered     │
│    ↓ 检查阈值触发 → 推送企微 + 虚拟下单                           │
│    ↓ 更新 watchlist_history.last_alert_at / alert_count         │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│                      数据存储层                                   │
├─────────────────────────────────────────────────────────────────┤
│  config.yaml (规则真源)                                          │
│    - real_portfolio_rules (持仓规则)                            │
│    - watchlist.user_manual (用户观察池)                         │
│    - watchlist.auto_discovered (系统观察池)                     │
│                                                                  │
│  sim_live_mirror.db                                             │
│    - sim_positions (持仓数量/成本/现价)                          │
│    - watchlist_history (观察池历史/淘汰记录)                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 实施计划

### Phase 3.1: 数据结构改造
1. **config.yaml 改造**：
   - 添加 `watchlist.user_manual` 和 `watchlist.auto_discovered` 分层
   - 迁移现有 `watchlist` 到 `user_manual`（向后兼容）
   - 添加元数据字段：`discovery_score`, `last_alert_at`, `alert_count`, `max_inactive_days`

2. **数据库扩展**：
   - 创建 `watchlist_history` 表
   - 初始化现有观察池数据

3. **sim/portfolio.py 改造**：
   - `load_watchlist_rules()` 支持分层加载
   - 新增 `update_watchlist_alert()` 更新 `last_alert_at`
   - 新增 `add_to_watchlist()` / `remove_from_watchlist()`

### Phase 3.2: 盘中异动扫描
1. **新增 scripts/intraday_scanner.py**：
   - 实现量价突破/涨停回落/超跌反弹 3 种异动识别
   - 自动加入 `auto_discovered` 观察池
   - 推送企微通知

2. **注册 Windows 计划任务**：
   - 创建 `QuantLearn_IntradayScanner` 任务
   - 每 30 分钟运行一次（仅交易时段）

### Phase 3.3: 自动淘汰机制
1. **新增 scripts/cleanup_watchlist.py**：
   - 实现无触发淘汰（7 天）
   - 实现趋势破位淘汰（trend_break）
   - 实现低分衰减淘汰（score < 60 且 3 天无触发）

2. **注册 Windows 计划任务**：
   - 创建 `QuantLearn_CleanupWatchlist` 任务
   - 每日 8:00 运行

3. **portfolio_alert.py 改造**：
   - 触发阈值时更新 `watchlist_history.last_alert_at`
   - 增量更新 `alert_count`

### Phase 3.4: 兼容性保证
1. **向后兼容**：
   - `sim/portfolio.py` 的 `load_all_alert_rules()` 保持接口不变
   - 内部实现改为分层加载 `user_manual` + `auto_discovered`

2. **渐进迁移**：
   - 不破坏现有 `portfolio_alert.py` / `morning_scanner.py` 功能
   - 先部署新功能，验证后再逐步淘汰旧结构

---

## 5. 其他优化建议

### 5.1 代码质量
- **日志规范化**：统一使用 `logging` 模块，避免 `print()` 混用
- **错误处理**：所有网络请求（新浪行情/AKShare）添加重试 + 降级策略
- **类型注解**：关键函数添加 type hints（Python 3.10+）

### 5.2 性能优化
- **批量行情拉取**：`intraday_scanner.py` 使用 `fetch_all_realtime()` 一次拉全市场，避免逐只拉取
- **缓存机制**：MA/ATR 计算结果缓存到 Redis（可选，需要额外部署）
- **并行扫描**：`ThreadPoolExecutor` 并行处理 K 线计算（已有，保持）

### 5.3 可观测性
- **指标监控**：
  - 观察池膨胀率（auto_discovered 数量 / user_manual 数量）
  - 淘汰率（移除数 / 新增数）
  - 异动捕获率（盘中扫描命中数 / 全市场异动数）
  
- **告警阈值**：
  - 观察池总数 > 50 → 告警（过度膨胀）
  - 连续 3 日无盘中异动 → 告警（扫描器失效？）

### 5.4 风控增强
- **单日新增限额**：`auto_discovered` 每日最多新增 5 只（避免盲目扩张）
- **评分阈值**：discovery_score < 70 的不自动加入（需人工审核）
- **黑名单**：曾经淘汰过的股票 30 天内不再自动加入

### 5.5 用户体验
- **企微交互增强**：
  - 推送消息支持「加入观察」按钮（企微模板卡片）
  - 回复「删除 600519」可快速移除观察股
  
- **Web 仪表盘**（可选）：
  - 观察池可视化管理（Flask 轻量 Web）
  - 淘汰历史查询
  - 评分趋势图

---

## 6. 风险评估

### 6.1 技术风险
- **行情接口限流**：AKShare / 新浪行情有频率限制
  - **缓解**：错峰扫描（盘中扫描间隔 30 分钟）+ 限流重试

- **配置文件冲突**：多脚本并发写 `config.yaml` 可能冲突
  - **缓解**：引入文件锁（`fcntl` / `filelock` 库）

### 6.2 业务风险
- **误加噪音股**：盘中异动可能捕获短期炒作股
  - **缓解**：提高 discovery_score 阈值（≥ 70）+ 快速淘汰（3 天无触发）

- **过度依赖自动化**：系统推荐不等于买入建议
  - **缓解**：推送消息明确标注「仅供参考」+ 盈亏比计算

---

## 7. 验收标准

### 7.1 功能验收
- [ ] `config.yaml` 支持分层 `user_manual` / `auto_discovered`
- [ ] `intraday_scanner.py` 能识别量价突破/涨停回落/超跌反弹
- [ ] 盘中异动自动加入观察池 + 推送企微
- [ ] 淘汰机制正常运行（7 天无触发 / 趋势破位）
- [ ] 观察池历史记录到 `watchlist_history` 表
- [ ] 现有 `portfolio_alert.py` 功能不受影响

### 7.2 性能验收
- [ ] 盘中扫描耗时 < 30 秒（800 只股票）
- [ ] 内存占用 < 200MB
- [ ] 数据库写入无阻塞（< 100ms）

### 7.3 稳定性验收
- [ ] 连续运行 5 个交易日无异常
- [ ] 行情接口失败时能降级（新浪 → BaoStock）
- [ ] Windows 计划任务正常触发

---

## 8. 后续规划

### 8.1 短期（1-2 周）
- 部署 `intraday_scanner.py` 和 `cleanup_watchlist.py`
- 优化 `morning_scanner.py` 与盘中扫描的协同
- 收集 1 周数据，评估异动捕获准确率

### 8.2 中期（1 个月）
- 引入机器学习模型（XGBoost）优化 discovery_score 计算
- 对接 TDX/通达信 Level-2 数据（盘口数据）
- 支持多账户策略（learn 账户自动下单 auto_discovered 股票）

### 8.3 长期（3 个月）
- 开发 Web 仪表盘（Flask + Vue）
- 接入企微应用（替代群机器人，支持按钮交互）
- 回测引擎支持观察池策略（Backtrader 回测 auto_discovered 收益）

---

## 附录 A：配置文件示例（完整版）

见 `config.yaml.new` 示例文件（待实施时创建）。

## 附录 B：数据库 Schema

见 `data/schema.sql`（待实施时创建）。

---

**END OF DOCUMENT**
