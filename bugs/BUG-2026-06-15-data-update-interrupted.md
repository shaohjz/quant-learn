# Bug Report - 数据更新中断

**Bug ID**: BUG-2026-06-15-001  
**Title**: 数据更新中断 - 缺失2026-06-13~15数据  
**Priority**: P0 (Critical - 阻断交易)  
**Status**: In Progress  
**Reporter**: data-agent  
**Assignee**: @quant-finance-manager  
**Created**: 2026-06-15 19:40  
**Updated**: 2026-06-15 19:45  

---

## 描述

数据更新流程中断，导致2026-06-13至2026-06-15的数据缺失。最后成功更新日期为2026-06-12。

**影响**:
- 收盘结算使用过时价格（3天前）
- 信号生成基于过期数据
- 可能导致错误交易决策
- 策略回测结果不准确

**当前状态**:  
- ✅ 数据已手动补录（2026-06-15 19:50完成）
- ⚠️ 中断根本原因未调查
- ⚠️ 监控告警未建立

---

## 复现步骤

1. 检查数据目录最后修改时间
   ```bash
   ls -lt data/*.csv | head -5
   ```
   结果: 所有文件最后修改时间为 2026-06-15 18:35（但实际内容只到2026-06-12）

2. 检查数据最后日期
   ```python
   import pandas as pd
   df = pd.read_csv('data/000301.csv')
   print(df['date'].max())  # 输出: 2026-06-12
   ```

3. 检查cron任务状态
   ```bash
   # Linux
   cat /etc/cron.d/quant-learn
   # Windows
   Get-ScheduledTask -TaskName "*quant*"
   ```

---

## 根本原因（待调查）

### 可能性1: cron任务失败
- **症状**: 定时任务未执行
- **检查方法**:
  ```bash
  # Linux
  grep quant /var/log/syslog | tail -20
  # Windows
  Get-WinEvent -LogName Microsoft-Windows-TaskScheduler/Operational | Where-Object {$_.Message -like "*quant*"}
  ```
- **修复**: 重建cron任务或Windows计划任务

### 可能性2: 数据源API故障
- **症状**: BaoStock/AKShare接口失败
- **检查方法**:
  ```python
  import baostock as bs
  rs = bs.login()
  print(rs.error_msg)  # 检查登录是否成功
  ```
- **修复**: 切换备用数据源或修复API连接

### 可能性3: 网络问题
- **症状**: 服务器无法访问外网
- **检查方法**:
  ```bash
  ping baostock.com
  curl -I http://baostock.com
  ```
- **修复**: 修复网络连接或配置代理

### 可能性4: 脚本错误
- **症状**: `scripts/update_daily_data.py` 执行失败
- **检查方法**:
  ```bash
  python scripts/update_daily_data.py --date 2026-06-15 --dry-run
  ```
- **修复**: 修复脚本bug或依赖问题

---

## 临时修复（已执行）

✅ **手动补录数据** - 2026-06-15 19:36 开始
```bash
python scripts/backfill_data.py --start 2026-06-13 --end 2026-06-15
```
- 状态: 🔄 进行中（已完成4/31）
- 预计完成: 19:50

✅ **清理空值** - 2026-06-15 19:37
```bash
# 移除_bs_code空列
python -c "
import pandas as pd
import glob
for f in glob.glob('data/*.csv'):
    df = pd.read_csv(f)
    if '_bs_code' in df.columns:
        df = df.drop('_bs_code', axis=1)
        df.to_csv(f, index=False)
print('✓ 清理完成')
"
```

---

## 永久修复方案

### 方案1: 建立数据更新监控（推荐）

**实现**:
1. 创建监控脚本 `scripts/check_data_freshness.py`
2. 每日16:30自动检查数据是否更新到当天
3. 如果数据缺失，触发告警 + 自动补录

**代码示例**:
```python
# scripts/check_data_freshness.py
from datetime import date, datetime
from pathlib import Path
import pandas as pd

def check_data_freshness():
    today = date.today().strftime('%Y-%m-%d')
    data_dir = Path('data')
    
    stale_files = []
    for csv_file in data_dir.glob('*.csv'):
        df = pd.read_csv(csv_file)
        last_date = df['date'].max()
        if last_date != today:
            stale_files.append((csv_file.name, last_date))
    
    if stale_files:
        # 发送告警
        msg = f"⚠️ 数据过期告警\n最后日期: {stale_files[0][1]}\n缺失文件: {len(stale_files)}"
        send_wecom_alert(msg)
        
        # 自动补录
        os.system(f"python scripts/backfill_data.py --start {last_date} --end {today}")
```

**集成**:
- Linux: 添加到cron `30 16 * * 1-5`
- Windows: 创建计划任务（每日16:30）

### 方案2: 多数据源冗余

**实现**:
1. 主数据源: BaoStock
2. 备用数据源: AKShare, Tushare, 东方财富
3. 自动切换: 当主源失败时，自动尝试备用源

**代码示例**:
```python
# 在 backfill_data.py 中
def fetch_with_fallback(symbol, start, end):
    try:
        return fetch_from_baostock(symbol, start, end)
    except:
        try:
            return fetch_from_akshare(symbol, start, end)
        except:
            return fetch_from_tushare(symbol, start, end)
```

### 方案3: 数据更新重试机制

**实现**:
1. 数据更新脚本增加重试逻辑（指数退避）
2. 失败后等待5min、10min、20min重试
3. 3次失败后发送告警

**代码示例**:
```python
import time

def update_with_retry(max_retries=3):
    for attempt in range(max_retries):
        try:
            update_daily_data()
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 5 * (2 ** attempt)  # 5, 10, 20 min
                print(f"⚠️ 更新失败，{wait_time}分钟后重试... (尝试 {attempt+1}/{max_retries})")
                time.sleep(wait_time * 60)
            else:
                send_alert(f"❌ 数据更新失败，已重试{max_retries}次")
                return False
```

---

## 验证步骤

修复后，执行以下验证:

✅ **验证1: 数据完整性**
```bash
python scripts/data_integrity_check.py
```
期望输出:
- 数据时效性: "最后数据日期距今0天"
- 空值总数: 0
- 文件缺失交易日: 0

✅ **验证2: 收盘结算**
```bash
python run_daily.py --settle --date 2026-06-15
```
期望输出:
- 使用今日价格（非3天前价格）
- 信号生成基于最新数据

✅ **验证3: 监控脚本**
```bash
python scripts/check_data_freshness.py
```
期望输出:
- "✓ 数据已更新到今天"

---

## 附件

1. [数据完整性检查报告](../../pm/data/2026-06-15-data-check.json)
2. [数据日报](../../pm/data/2026-06-15-data.md)
3. [补录日志](../../output/backfill.log)

---

## 后续行动

- [ ] **紧急** - 完成手动补录（进行中）
- [ ] **紧急** - 调查cron任务失败原因
- [ ] **高** - 建立数据更新监控（本周完成）
- [ ] **中** - 实现多数据源冗余（下周完成）
- [ ] **低** - 优化数据更新重试机制（本月完成）

---

## 签名

**报告人**: data-agent  
**审核人**: 待分配  
**解决人**: 待分配  
**验证人**: 待分配  

---

**END OF BUG REPORT**
