# PM 任务真源（Markdown）

- **活跃任务**：`pm/requirements/*.md`、`pm/bugs/*.md`（必须含 YAML frontmatter：`id/status/priority/...`）
- **归档**：`pm/archive/`（历史 `tasks_archive` 迁入）
- **索引**：[`BACKLOG.md`](./BACKLOG.md) — `python scripts/pm_cli.py list --write-backlog`
- **CLI**：`python scripts/pm_cli.py create|update|list|get`
- **禁止**：再往 `data/pm.db` 写任务（已从 git 移除；运行态 freshness 用 `data/ops_runtime.db`）

无 frontmatter 的旧长文仍可人工阅读，但**不进** `pm_cli list` / 日报统计。
