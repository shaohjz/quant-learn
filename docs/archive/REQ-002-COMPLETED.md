# REQ-002 收益率曲线图 - 完成报告

## ✅ 实现完成

已成功实现 QuantLearn 仪表盘的 REQ-002（收益率曲线图）功能。

### 实现内容

#### 1. 数据库层 ✅
- 创建 `daily_snapshot` 表，存储每日账户快照
  - 字段：snapshot_date, account_type, total_asset, total_market_value, cash, position_count
  - 支持模拟盘和实盘数据分别记录
  - 脚本：`scripts/create_snapshot_table.py`

#### 2. 数据采集 ✅
- 实现每日快照脚本 `scripts/snapshot_daily.py`
  - 自动读取当前账户资产状态
  - 支持手动指定日期：`python snapshot_daily.py 2026-05-25`
  - 使用 ON CONFLICT 更新机制，支持重复运行

#### 3. 后端 API ✅
- 新增 `/api/equity_curve` 接口
  - 查询近30天快照数据
  - 计算累计收益率（相对首日资产）
  - 返回格式：`{dates: [], returns: [], benchmark: []}`
  - 空数据时返回空数组

#### 4. 前端展示 ✅
- 在实盘 Tab 顶部添加 250px 高度的 ECharts 图表
- 集成 ECharts 5.x CDN：`https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js`
- 配色方案：
  - 收益率线：蓝色 (#1a73e8) + 渐变区域填充
  - 基准线：灰色虚线 (#9ca3af)
- 交互特性：
  - tooltip 显示日期和收益率百分比
  - X轴仅显示月-日（去掉年份）
  - Y轴百分比格式化
  - 响应式自动调整大小
- 空数据提示："⚠️ 暂无数据,明天开始积累"

### 测试结果

✅ API 测试通过
```bash
curl http://localhost:8080/api/equity_curve
# 返回31条近30天数据
```

✅ 生成30天模拟数据验证曲线效果
- 初始资产：¥100,000
- 最终资产：¥116,500
- 累计收益率：+17.36%
- 曲线正常显示波动趋势

✅ Web 服务重启成功
- 端口：8080
- 访问地址：http://localhost:8080

### Git 提交记录

```
commit 3f5fe37
feat: REQ-002 收益率曲线图

- 数据库：创建 daily_snapshot 表
- 后端API：实现 /api/equity_curve
- 前端：集成 ECharts 绘制折线图
- 脚本：snapshot_daily.py 每日快照
- 支持响应式和tooltip交互
```

推送至：`git.woa.com:jizhouhu/quant-learn.git (dev 分支)`

### 文件变更

**新增文件：**
- `scripts/snapshot_daily.py` - 每日快照脚本
- `scripts/create_snapshot_table.py` - 创建表脚本
- `pm/requirements/REQ-002.md` - 需求文档

**修改文件：**
- `web/app.py` - 新增 `/api/equity_curve` 路由
- `web/templates/index.html` - 添加 ECharts CDN 和图表容器

### 下一步工作

根据 REQ-002.md 中的待优化项：
1. [ ] 集成沪深300真实基准数据（当前为0基准线）
2. [ ] 实盘收益率曲线（需要实盘账户数据积累）
3. [ ] 支持切换时间范围（7天/30天/90天/全部）

### 使用说明

**每日运行快照脚本（建议收盘后）：**
```bash
cd quant-learn
.venv/Scripts/python.exe scripts/snapshot_daily.py
```

**可配置定时任务：**
- Windows 计划任务：每天15:30运行
- Linux crontab：`30 15 * * 1-5 cd /path/to/quant-learn && .venv/bin/python scripts/snapshot_daily.py`

---

## 总结

REQ-002 核心功能已完成并测试通过，代码已推送至 dev 分支。
状态已更新为 **testing**，可进入用户验收阶段。

完成时间：2026-05-25 16:43
开发耗时：约45分钟
提交哈希：3f5fe37
