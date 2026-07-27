# BUG: DailyGitSync 工作区脏时放弃 push（Last Result=128）

- 日期：2026-07-24
- 级别：P1（会导致台账推送 SLO 失败，今日靠守夜人工补 push）
- 组件：`scripts/daily_git_sync.py` / `daily_git_sync_runner.bat`

## 现象

18:45 `QuantLearn_DailyGitSync` Last Result=128。日志尾部：

```
UnicodeDecodeError: 'gbk' codec can't decode byte 0x98 in position 85
[daily_git_sync] committed: chore(daily): 2026-07-24 交易台账/PM队列/测试与运维落盘
error: cannot pull with rebase: You have unstaged changes.
error: Please commit or stash them.
[daily_git_sync] pull --rebase 失败，未 push
```

commit 成功但 push 被跳过 → 本地 ahead 1，远程缺最新台账。

## 根因

1. 工作区存在非白名单脏文件（scripts/*.py 未提交、output 日志、data/pm.db），
   `git pull --rebase` 拒绝执行，脚本据此放弃 push。
2. subprocess 读子进程输出按 GBK 解码，遇 UTF-8 输出崩读线程（非致命但污染日志/返回码）。

## 修复建议（Cursor）

1. `git pull --rebase --autostash origin master`，或 rebase 前 `git stash -u` 仅针对非白名单路径；
   失败时仍尝试 `git push`（本地领先且远程无分叉时 fast-forward push 是安全的）。
2. 所有 subprocess 调用统一 `encoding='utf-8', errors='replace'`。
3. push 失败时返回非 0 并在日志显式打印 `PUSH FAILED`，便于守夜 grep。

## 今日处置

守夜按 §8.1 审查 `origin/master..HEAD` 仅白名单文件后手动 `git push origin master`，
SLO 达成。详见 `pm/ops/2026-07-24-nightwatch.md`。
