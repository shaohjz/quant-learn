# BUG: DailyGitSync 定时任务 push 失败（Host key verification failed）

- **日期**：2026-07-30
- **级别**：P1（每日 18:45 自动推送失效，SLO 依赖守夜手动兜底）
- **现象**：`schtasks /run /tn QuantLearn_DailyGitSync` 后，`output/daily_git_sync.log` 显示 commit 成功但：

  ```
  Host key verification failed.
  fatal: Could not read from remote repository.
  [daily_git_sync] PUSH FAILED
  ```

- **对照**：同机交互 shell 中 `git push origin master` 成功（180a4e42..acd31f5f）。
- **根因推测**：schtasks 运行用户/环境的 `~/.ssh/known_hosts` 中没有 `git.woa.com` 的 host key（或 HOME/USERPROFILE 环境变量不同导致读不到）。
- **修复建议（Cursor/主人处理）**：
  1. 确认 schtasks 任务运行账户；在该账户环境下执行一次 `ssh -T git@git.woa.com` 接受 host key，或
  2. 在 runner bat 中显式设置 `GIT_SSH_COMMAND=ssh -o UserKnownHostsFile=C:\Users\Administrator\.ssh\known_hosts`，或
  3. 将远程改为 HTTPS + 凭据管理器。
- **验收标准**：次日 18:45 DailyGitSync 日志出现 push 成功且 origin/master 出现当日 chore(daily) 提交，无需守夜补推。
