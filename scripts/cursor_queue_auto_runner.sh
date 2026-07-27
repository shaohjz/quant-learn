#!/usr/bin/env bash
# cursor_queue_auto_runner.sh — 本机 Linux 消费 pm/cursor_queue（方案 A）
#
# 职责：cron 定时拉最新 master → 开 feature 分支 → 调 Cursor Agent CLI 无头修码
#       → 有新 commit 才 push feature 分支（绝不 push master）→ 可选建 MR → 写 ops 日志。
#       无产出不 push；跑完尽量切回 master。
#
# 安装 Cursor Agent CLI（若本机没有 agent）：
#   curl https://cursor.com/install -fsS | bash
#   export PATH="$HOME/.local/bin:$PATH"
#   agent --version
# 认证：export CURSOR_API_KEY=...  （或 agent login）
# 文档：https://cursor.com/docs/cli/installation
#
# 环境变量：
#   CURSOR_API_KEY           必填（真跑时）；缺则优雅退出并提示
#   CURSOR_AUTO_MAX_ITEMS    默认 1（最多处理队列前 N 项，防一次改爆）
#   CURSOR_AUTO_DRY_RUN=1    只演练：拉代码/找队列/建分支计划，不调 agent、不 push
#   CURSOR_AUTO_SKIP_PULL=1  跳过 git fetch/pull（调试用）
#   CURSOR_AUTO_MODEL        可选，传给 agent --model
#   GITLAB_TOKEN / GF_TOKEN  可选；有 glab 或 curl+token 时尝试开 MR
#
# 示例 crontab（本机 Linux，不是产机 Windows schtasks；Asia/Shanghai）：
#   # 交易日 19:30：等 18:45 DailyGitSync 把 cursor_queue 推进 master 后再消费
#   30 19 * * 1-5  cd /data/shaohjz/quant-learn && \
#     CURSOR_API_KEY=*** ./scripts/cursor_queue_auto_runner.sh >> output/cursor_queue_auto.log 2>&1
#
# 安全红线：只 push feat/cursor-auto-*；禁止 force push；禁止改 config.local* / *.db / 密钥。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MAX_ITEMS="${CURSOR_AUTO_MAX_ITEMS:-1}"
DRY_RUN="${CURSOR_AUTO_DRY_RUN:-0}"
SKIP_PULL="${CURSOR_AUTO_SKIP_PULL:-0}"
TODAY="$(date +%F)"
TODAY_COMPACT="$(date +%Y%m%d)"
TS="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="${ROOT}/output/cursor_queue_auto.log"
OPS_FILE="${ROOT}/pm/ops/${TODAY}-cursor-auto.md"
LOCK_DIR="${ROOT}/output/.cursor_queue_auto.lock"

mkdir -p "${ROOT}/output" "${ROOT}/pm/ops"

log() {
  local line="[$(date '+%F %T')] $*"
  echo "$line" | tee -a "$LOG_FILE"
}

ops_append() {
  mkdir -p "$(dirname "$OPS_FILE")"
  if [[ ! -f "$OPS_FILE" ]]; then
    cat >"$OPS_FILE" <<EOF
# Cursor 队列自动消费 ${TODAY}

> 本机 runner：\`scripts/cursor_queue_auto_runner.sh\`（方案 A）
> 只推 feature 分支，**绝不**自动推 master；MR 需人工验收。

EOF
  fi
  echo "$*" >>"$OPS_FILE"
}

die() {
  log "ERROR: $*"
  ops_append "- **失败** (${TS}): $*"
  exit 1
}

release_lock() {
  if [[ -d "$LOCK_DIR" ]]; then
    rm -rf "$LOCK_DIR" 2>/dev/null || true
  fi
}

# --- 0a. 排他锁（防 cron 重叠）---
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "另一实例仍在跑（锁 ${LOCK_DIR}），退出 0"
  ops_append "- ${TS}: 锁占用，跳过"
  exit 0
fi
echo "$$" >"${LOCK_DIR}/pid"
trap release_lock EXIT

checkout_master_quiet() {
  # 收尾切回 master；失败只告警
  if git show-ref --verify --quiet refs/heads/master; then
    if git checkout master >/dev/null 2>&1; then
      if [[ "$SKIP_PULL" != "1" ]]; then
        git pull --ff-only origin master >/dev/null 2>&1 || log "警告：收尾 pull --ff-only master 失败（可忽略）"
      fi
      log "已切回 master"
      return 0
    fi
  elif git show-ref --verify --quiet refs/heads/main; then
    if git checkout main >/dev/null 2>&1; then
      if [[ "$SKIP_PULL" != "1" ]]; then
        git pull --ff-only origin main >/dev/null 2>&1 || log "警告：收尾 pull --ff-only main 失败（可忽略）"
      fi
      log "已切回 main"
      return 0
    fi
  fi
  log "警告：无法切回 master/main"
  return 1
}

# --- 0. 找 Cursor Agent CLI ---
find_agent() {
  if command -v agent >/dev/null 2>&1; then
    command -v agent
    return 0
  fi
  if command -v cursor-agent >/dev/null 2>&1; then
    command -v cursor-agent
    return 0
  fi
  if [[ -x "${HOME}/.local/bin/agent" ]]; then
    echo "${HOME}/.local/bin/agent"
    return 0
  fi
  if [[ -x "${HOME}/.local/bin/cursor-agent" ]]; then
    echo "${HOME}/.local/bin/cursor-agent"
    return 0
  fi
  return 1
}

AGENT_BIN=""
if AGENT_BIN="$(find_agent)"; then
  log "agent CLI: ${AGENT_BIN} ($("${AGENT_BIN}" --version 2>/dev/null || echo unknown))"
else
  msg="未找到 Cursor Agent CLI（agent / cursor-agent）。安装：curl https://cursor.com/install -fsS | bash ；并把 ~/.local/bin 加入 PATH。"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "DRY_RUN: ${msg}"
  else
    die "$msg"
  fi
fi

# --- 1. 认证检查（dry-run 可跳过）---
if [[ "$DRY_RUN" != "1" ]]; then
  if [[ -z "${CURSOR_API_KEY:-}" ]]; then
    # agent login 也可能已登录；用 status 探测（失败则退出）
    if ! "${AGENT_BIN}" status >/dev/null 2>&1 && ! "${AGENT_BIN}" whoami >/dev/null 2>&1; then
      die "无 CURSOR_API_KEY 且 agent 未登录。请 export CURSOR_API_KEY=... 或执行 agent login。避免无密钥硬跑烧钱。"
    fi
  else
    log "CURSOR_API_KEY: present"
  fi
else
  if [[ -n "${CURSOR_API_KEY:-}" ]]; then
    log "DRY_RUN: CURSOR_API_KEY=present（不会调用 agent）"
  else
    log "DRY_RUN: CURSOR_API_KEY=absent（ok）"
  fi
fi

# --- 2. 必须在干净-ish 的 git 仓库；拉最新 master ---
[[ -d .git ]] || die "不是 git 仓库: ${ROOT}"

if [[ "$SKIP_PULL" != "1" ]]; then
  log "git fetch + pull --ff-only origin master"
  git fetch origin
  # 确保在 master 上再开分支（若当前在别的分支且干净，可切回）
  current="$(git branch --show-current || true)"
  if [[ "$current" != "master" && "$current" != "main" ]]; then
    if [[ -n "$(git status --porcelain)" ]]; then
      die "当前分支 ${current} 有未提交改动，拒绝自动切 master。请先清理。"
    fi
    if git show-ref --verify --quiet refs/heads/master; then
      git checkout master
    elif git show-ref --verify --quiet refs/heads/main; then
      git checkout main
    else
      die "找不到 master/main 本地分支"
    fi
  fi
  if ! git pull --ff-only origin master 2>/dev/null; then
    if ! git pull --ff-only origin main 2>/dev/null; then
      die "git pull --ff-only 失败（有分叉或网络问题）。拒绝强拉。"
    fi
  fi
else
  log "SKIP_PULL=1，跳过 fetch/pull"
fi

# --- 3. 找今日或最近的 cursor_queue ---
QUEUE_DIR="${ROOT}/pm/cursor_queue"
QUEUE_FILE=""
if [[ -f "${QUEUE_DIR}/${TODAY}.md" ]]; then
  QUEUE_FILE="${QUEUE_DIR}/${TODAY}.md"
else
  # 最近一份（按文件名日期倒序）
  QUEUE_FILE="$(ls -1 "${QUEUE_DIR}"/20[0-9][0-9]-*.md 2>/dev/null | sort -r | head -1 || true)"
fi

if [[ -z "$QUEUE_FILE" || ! -f "$QUEUE_FILE" ]]; then
  log "无 pm/cursor_queue 队列文件，静默退出 0"
  ops_append "- ${TS}: 无队列文件，跳过"
  exit 0
fi

QUEUE_REL="${QUEUE_FILE#${ROOT}/}"
log "队列文件: ${QUEUE_REL}"

# --- 4. feature 分支 ---
BASE_BRANCH="feat/cursor-auto-${TODAY_COMPACT}"
BRANCH="$BASE_BRANCH"
if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
  # 已存在：若相对 master 无新 commit 可复用；否则加时间戳后缀
  if [[ -n "$(git log "master..${BRANCH}" --oneline 2>/dev/null || true)" ]] \
     || [[ -n "$(git status --porcelain)" ]]; then
    BRANCH="${BASE_BRANCH}-${TS}"
  fi
fi

if [[ "$DRY_RUN" == "1" ]]; then
  log "DRY_RUN: 将使用分支 ${BRANCH}，MAX_ITEMS=${MAX_ITEMS}，队列=${QUEUE_REL}"
  ops_append "- ${TS}: DRY_RUN 计划分支 \`${BRANCH}\`，队列 \`${QUEUE_REL}\`，max=${MAX_ITEMS}"
  log "DRY_RUN 完成，未调 agent / 未 push"
  exit 0
fi

if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
  git checkout "$BRANCH"
else
  git checkout -b "$BRANCH"
fi
log "分支: ${BRANCH}"
ops_append "- ${TS}: 分支 \`${BRANCH}\`，队列 \`${QUEUE_REL}\`，max_items=${MAX_ITEMS}"

# --- 5. 构造硬约束 prompt ---
PROMPT=$(cat <<EOF
你在仓库 ${ROOT} 工作。这是无头自动消费 Cursor 队列任务。

【唯一任务】
1. 读 ${QUEUE_REL}（若提到「今天」即此文件）。
2. 严格按 P0 → P1 顺序处理，**最多做 ${MAX_ITEMS} 项**（默认少做，防一次改爆）。跳过已打勾/已 done、以及「本周不做」「不要动」区块。
3. 每项：读对应 REQ/BUG + PLAN（无则先写最短 10 行方案到 pm/dev/）→ 改代码 → 能跑则跑验收 → 用 pm_cli 更新状态（若可用）→ 队列该项打勾 → **每项单独 commit**。
4. 遵守仓库现有风格与 .cursor/rules；改调度/runner/cron/守夜相关时必须同改 docs/DEPLOYMENT.md（deploy-docs-first）。

【硬红线】
- 禁止 force push；禁止直接推 master/main；禁止 \`git push --force\`。
- 禁止改 config.local*、*.db、密钥、webhook、.env。
- 不要实现无关大重构；不要删 OpenClaw 主流程提示词。
- 做完后停在当前 feature 分支；**不要** git push（外层脚本会 push feature 分支）。
- 若队列为空或无可做项：写一句说明到 pm/ops/${TODAY}-cursor-auto.md 后退出即可。

【交付】
- 简短总结：做了哪些项、commit hash、剩余未做项。
- 追加几行到 pm/ops/${TODAY}-cursor-auto.md。
EOF
)

AGENT_ARGS=(-p --force --trust --workspace "$ROOT")
if [[ -n "${CURSOR_AUTO_MODEL:-}" ]]; then
  AGENT_ARGS+=(--model "$CURSOR_AUTO_MODEL")
fi

log "调用 agent（print/force），max_items=${MAX_ITEMS}"
set +e
"${AGENT_BIN}" "${AGENT_ARGS[@]}" "$PROMPT" 2>&1 | tee -a "$LOG_FILE"
AGENT_RC=${PIPESTATUS[0]}
set -e

if [[ "$AGENT_RC" -ne 0 ]]; then
  ops_append "- ${TS}: agent 退出码 ${AGENT_RC}"
  die "agent 失败，exit=${AGENT_RC}"
fi

# --- 6. 若有改动未提交，兜底提示（不自动乱 commit；agent 应已 commit）---
DIRTY="$(git status --porcelain || true)"
if [[ -n "$DIRTY" ]]; then
  log "警告：工作区仍有未提交改动；请人工检查。不自动 commit。"
  ops_append "- ${TS}: 警告 — agent 后仍有未提交改动"
fi

# --- 6b. 无新 commit 且工作区干净 → 不 push ---
BASE_REF="master"
if ! git show-ref --verify --quiet refs/heads/master; then
  BASE_REF="main"
fi
AHEAD_COUNT="$(git rev-list --count "${BASE_REF}..HEAD" 2>/dev/null || echo 0)"
if [[ "${AHEAD_COUNT}" -eq 0 && -z "$DIRTY" ]]; then
  log "无新 commit（相对 ${BASE_REF}），跳过 push"
  ops_append "- ${TS}: 无产出，不 push"
  checkout_master_quiet || true
  log "完成（空跑）。日志 ${LOG_FILE}；ops ${OPS_FILE}"
  exit 0
fi
if [[ "${AHEAD_COUNT}" -eq 0 && -n "$DIRTY" ]]; then
  log "无新 commit 但工作区脏，拒绝 push；请人工处理"
  ops_append "- ${TS}: 无 commit 且工作区脏，不 push"
  exit 1
fi

# --- 7. push feature 分支（绝不 push master）---
CURRENT="$(git branch --show-current)"
if [[ "$CURRENT" == "master" || "$CURRENT" == "main" ]]; then
  die "安全闸：当前在 ${CURRENT}，拒绝自动 push。预期 feature 分支。"
fi
if [[ "$CURRENT" != "$BRANCH" ]]; then
  log "警告：当前分支 ${CURRENT} ≠ 预期 ${BRANCH}；仍只 push 当前非 master 分支"
  BRANCH="$CURRENT"
fi

log "git push -u origin HEAD (${BRANCH})，ahead=${AHEAD_COUNT}"
if ! git push -u origin HEAD; then
  die "push feature 分支失败"
fi
ops_append "- ${TS}: 已 push \`origin/${BRANCH}\`（非 master，ahead=${AHEAD_COUNT}）"

# --- 8. 可选开 MR ---
MR_OK=0
if command -v glab >/dev/null 2>&1; then
  if glab mr create --fill --target-branch master --title "cursor-auto: ${TODAY}" \
      --description "自动消费 \`${QUEUE_REL}\`（最多 ${MAX_ITEMS} 项）。请人工验收，勿自动合并。" 2>&1 | tee -a "$LOG_FILE"; then
    MR_OK=1
    ops_append "- ${TS}: 已用 glab 创建 MR（请人工验收）"
  fi
fi

if [[ "$MR_OK" -eq 0 ]]; then
  TOKEN="${GITLAB_TOKEN:-${GF_TOKEN:-}}"
  if [[ -n "$TOKEN" ]] && command -v curl >/dev/null 2>&1; then
    # 工蜂 GitLab API（项目路径需 URL encode）
    PROJECT_PATH="jizhouhu%2Fquant-learn"
    API="${GITLAB_API_URL:-https://git.woa.com/api/v4}"
    set +e
    curl -sS --fail -X POST \
      -H "PRIVATE-TOKEN: ${TOKEN}" \
      -H "Content-Type: application/json" \
      "${API}/projects/${PROJECT_PATH}/merge_requests" \
      -d "{\"source_branch\":\"${BRANCH}\",\"target_branch\":\"master\",\"title\":\"cursor-auto: ${TODAY}\",\"description\":\"自动消费 ${QUEUE_REL}。请人工验收。\"}" \
      2>&1 | tee -a "$LOG_FILE"
    CURL_RC=$?
    set -e
    if [[ "$CURL_RC" -eq 0 ]]; then
      MR_OK=1
      ops_append "- ${TS}: 已用 curl+token 创建 MR（请人工验收）"
    fi
  fi
fi

if [[ "$MR_OK" -eq 0 ]]; then
  log "无 glab/token 或建 MR 失败 → 请人工开 MR：origin/${BRANCH} → master"
  ops_append "- ${TS}: **请人工开 MR**：\`${BRANCH}\` → \`master\`"
fi

checkout_master_quiet || true

log "完成。分支 origin/${BRANCH}；日志 ${LOG_FILE}；ops ${OPS_FILE}"
exit 0
