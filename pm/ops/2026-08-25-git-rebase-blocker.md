# Ops 记录 — git rebase 卡死根因（2026-08-25）

> 由 OpenClaw 日报 Agent 在跑 Evening sync 时发现并记录。非 SLO 失败（日报已入库）。

## 现象

`QuantLearn_DailyGitSyncEvening`（同 bat，跑 `scripts/daily_git_sync.py`）执行
`git pull --rebase --autostash` 时报错并反复残留 `.git/rebase-merge`：

```
fatal: It seems that there is already a rebase-merge directory ...
error: unable to unlink old 'output/pm_web.log': Invalid argument
fatal: could not reset --hard
```

→ 每次 pull 的 `reset --hard` 无法 unlink 被占用的 `output/pm_web.log`，
rebase 残留未清，下一个定时器再 pull 又被同一报错卡住（雪球）。

## 根因

`output/pm_web.log` 被 **3 个 `python.exe web/app.py` 进程常驻占用**（PID 3132 / 32860 / 15884），
该文件被 git 跟踪，pull 时 `reset --hard` 必须 unlink 它才能覆盖 → 被锁 → 失败。

## 为什么今天日报仍成功入库

`daily_git_sync.py` 在 pull 失败后有兜底 `git push` 分支：本地白名单提交（含
`daily_reports/2026-08-25-*.md`）已领先远程 → 兜底 push 成功 → 远程 commit `73577d74`
含两份日报。**SLO 满足，未触发【量化失职-日报未入库】。**

## 处置建议（需主人确认，Agent 未擅自 kill）

1. **停掉重复/占用 `pm_web.log` 的 web/app.py 进程**（3 个实例疑似重复启动），
   或把 `output/pm_web.log` 改写到 git 忽略路径（如 `output/.logs/` 或加 `.gitignore`）。
2. 当前 `.git/rebase-merge` 已由 Agent 清理（HEAD 停在 master `73577d74`，与远程一致），
   工作树不再处于 rebase 中。
3. 建议：将 `output/pm_web.log`、`output/*_watchdog*.log`、`output/portfolio_alert.log`
   等纯运行日志移出 git 跟踪（`.gitignore` + `git rm --cached`），从源头消除 unlink 锁。

待主人确认后，可删除 PM web 重复实例或调整日志路径，使次日 18:45/20:30 sync 不再残留 rebase。
