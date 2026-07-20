# BUG-20260710-001: 每日复盘/watchlist 脚本因 GBK 编码错误崩溃

**发现日期**: 2026-07-14
**来源**: pm_watchdog_runner.log / daily_review_runner.log / generate_next_watchlist_cron.log
**严重程度**: P1（影响每日复盘和 watchlist 生成）

## 现象

`daily_review_runner.log` 和 `generate_next_watchlist_cron.log` 中反复出现 GBK 编码错误：

```
UnicodeEncodeError: 'gbk' codec can't encode character '\U0001f4b0' in position 236: illegal multibyte sequence
```

脚本在打印包含 emoji 或中文的日志到 stdout 时，Windows 控制台 codepage 非 UTF-8 导致崩溃。

## 影响

- 每日复盘脚本 `daily_review_runner` 执行失败
- 次日 watchlist 生成脚本 `generate_next_watchlist_cron` 执行失败
- 影响复盘报告和 watchlist 的自动生成

## 根因

Windows 中文系统默认 codepage 为 GBK，而脚本中 print/logging 输出了 emoji（如 💰）或中文，导致编码转换失败。

## 修复建议

1. 在 Python 脚本入口处设置环境变量 `PYTHONIOENCODING=utf-8`
2. 或重定向 stdout 编码：`sys.stdout.reconfigure(encoding='utf-8')`
3. 或在调用脚本时设置 `$env:PYTHONIOENCODING='utf-8'`

## 受影响的脚本

- `scripts/daily_review_runner.py`（或相关复盘脚本）
- `scripts/generate_next_watchlist_cron.py`（或相关 watchlist 脚本）

## 相关日志

- `output/daily_review_runner.log`
- `output/generate_next_watchlist_cron.log`
- `output/pm_watchdog_runner.log`
