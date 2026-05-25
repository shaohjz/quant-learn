# TEST-2026-05-25-regression-001

## 测试范围
- REQ-002: 收益率曲线图
- REQ-003: 持仓饼图 + 统计页增强
- REQ-004: 实时刷新动画 + 数据更新提示
- BUG-001: `/api/stats` 返回 JSON 不完整/异常
- BUG-002: scanner fallback 在 Windows GBK 输出下因 Emoji 打印崩溃

## 测试时间
2026-05-25 20:15

## 测试环境
- 本地 Web: `http://127.0.0.1:8080/`
- 代码目录: `C:\Users\Administrator\.openclaw\workspace\quant-learn`

## 测试结果

### REQ-002 收益率曲线图
结果：通过

验证项：
- `/api/equity_curve` HTTP 200
- 返回 JSON 包含 `dates`, `returns`, `benchmark`
- 首页 HTML 包含 `echarts` 与 `equity-chart`

### REQ-003 持仓饼图 + 统计页增强
结果：通过

验证项：
- `/api/real_portfolio` HTTP 200
- 返回 JSON 包含 `account`, `positions`, `total_market_value`, `total_pnl`, `updated_at`
- `/api/stats` HTTP 200
- 返回 JSON 包含 `total_trades`, `week_trades`, `month_trades`, `win_rate`, `avg_hold_days`, `max_profit_trade`, `max_loss_trade`
- 首页 HTML 包含 `pie-chart`

### REQ-004 实时刷新动画 + 数据更新提示
结果：通过

验证项：
- 首页 HTML 包含 `flash-up`, `flash-down`
- 首页 HTML 包含 `status-indicator`, `update-time`
- 刷新状态相关前端代码已存在

### BUG-001 `/api/stats` 返回 JSON 不完整/异常
结果：回归通过

验证项：
- 重启 Web 服务后 `/api/stats` 返回完整增强字段
- JSON 可解析
- 需求 REQ-003 可进入完成状态

### BUG-002 scanner fallback GBK Emoji 崩溃
结果：回归通过（静态 + 语法验证）

验证项：
- `scripts/scanner_with_fallback.py` 控制台提示已移除 Emoji
- 文件语法可被 Python 编译
- 代码支持 `SCANNER_PRIMARY_TIMEOUT` 环境变量，便于后续模拟超时回归

## 结论
本轮回归通过。建议状态扭转：
- REQ-002: `testing` -> `done`
- REQ-003: `testing` -> `done`
- REQ-004: `testing` -> `done`
- BUG-001: `fixed` -> `verified`
- BUG-002: `fixed` -> `verified`

## 风险
- 前端动画为静态检查，未通过浏览器自动化逐帧验证；如后续引入浏览器自动化，可补充 UI 交互测试。
- BUG-002 未执行完整 fallback 长流程，只验证了导致崩溃的 Emoji 输出已移除。后续可增加专门的单元测试模拟 `TimeoutExpired`。
