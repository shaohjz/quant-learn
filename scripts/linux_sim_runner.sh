#!/usr/bin/env bash
# linux_sim_runner.sh — 本机 Linux 长期模拟（非产机）
#
# 职责：独立 DB（data/sim_local.db）+ 产物隔离（output/linux_sim/）跑
#       #1 learn（Pulse→portfolio_alert）+ #3 swing（池/扫描/盯盘/收盘）。
#       默认 --no-push，不与产机企微双推；不跑 DailyGitSync。
#
# 用法：
#   ./scripts/linux_sim_runner.sh init
#   ./scripts/linux_sim_runner.sh recalibrate|pool|pulse|swing_daily|journal|close
#   ./scripts/linux_sim_runner.sh day_close   # swing_daily + journal + close
#   LINUX_SIM_PUSH=1 ./scripts/linux_sim_runner.sh pool   # 可选推企微（标题带【本机Linux】）
#
# crontab 见 docs/DEPLOYMENT.md「本机 Linux 长期模拟」
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8
export QUANT_DB_PATH="${QUANT_DB_PATH:-$ROOT/data/sim_local.db}"
export QUANT_ARTIFACT_ROOT="${QUANT_ARTIFACT_ROOT:-$ROOT/output/linux_sim}"
PUSH_MODE="${LINUX_SIM_PUSH:-0}"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "ERROR: 缺少 $PY ，先: python3 -m venv .venv && . .venv/bin/activate && pip install -e '.[research,dev]'" >&2
  exit 1
fi

TODAY="$(date +%F)"
TODAY_COMPACT="$(date +%Y%m%d)"
NOW_HM="$(date +%H%M)"
LOG_DIR="${QUANT_ARTIFACT_ROOT}/logs"
mkdir -p "$LOG_DIR" "$QUANT_ARTIFACT_ROOT"

log() {
  echo "[$(date '+%F %T')] $*"
}

push_args=()
title_prefix=""
if [[ "$PUSH_MODE" != "1" ]]; then
  push_args+=(--no-push)
else
  title_prefix="【本机Linux】"
fi

# 盘中会话窗口（Asia/Shanghai）：09:30–11:30、13:00–15:00
# cron 可能在整点触发；pulse 额外过滤午休与开盘前/收盘后
in_pulse_session() {
  local hm="$NOW_HM"
  # 09:35–11:30
  if [[ "$hm" -ge 935 && "$hm" -le 1130 ]]; then
    return 0
  fi
  # 13:00–14:50
  if [[ "$hm" -ge 1300 && "$hm" -le 1450 ]]; then
    return 0
  fi
  return 1
}

run_locked() {
  local lock_name="$1"
  shift
  local lock_dir="${QUANT_ARTIFACT_ROOT}/.lock_${lock_name}"
  if ! mkdir "$lock_dir" 2>/dev/null; then
    log "锁占用 ${lock_dir}，跳过: $*"
    return 0
  fi
  # shellcheck disable=SC2064
  trap "rmdir '$lock_dir' 2>/dev/null || true" EXIT
  "$@"
  local rc=$?
  rmdir "$lock_dir" 2>/dev/null || true
  trap - EXIT
  return $rc
}

cmd_init() {
  log "init DB=$QUANT_DB_PATH artifact=$QUANT_ARTIFACT_ROOT"
  "$PY" -c "from sim.db import init_tables; init_tables(); print('init_tables ok', __import__('os').environ.get('QUANT_DB_PATH'))"
  "$PY" -u scripts/reset_account.py
  log "accounts:"
  "$PY" - <<'PY'
import sqlite3, os
con = sqlite3.connect(os.environ["QUANT_DB_PATH"])
for r in con.execute("SELECT id, account_name, cash, total_value, initial_cash FROM sim_account ORDER BY id"):
    print(" ", r)
PY
}

cmd_recalibrate() {
  local logf="${LOG_DIR}/recalibrate-${TODAY_COMPACT}.log"
  log "recalibrate → $logf"
  "$PY" -u scripts/daily_recalibrate.py >>"$logf" 2>&1
}

cmd_pool() {
  local logf="${LOG_DIR}/pool-${TODAY_COMPACT}.log"
  log "pool → $logf"
  "$PY" -u scripts/swing_pool_builder.py --max-pool 50 --min-score 70 --mode auto --force >>"$logf" 2>&1
  local title="${title_prefix}盘前波段扫描"
  if [[ ${#push_args[@]} -gt 0 ]]; then
    "$PY" -u scripts/swing_auto.py --title "$title" "${push_args[@]}" >>"$logf" 2>&1
  else
    "$PY" -u scripts/swing_auto.py --title "$title" >>"$logf" 2>&1
  fi
}

cmd_pulse() {
  if ! in_pulse_session; then
    log "pulse 非盘中会话窗口 (${NOW_HM})，跳过"
    return 0
  fi
  local logf="${LOG_DIR}/pulse-${TODAY_COMPACT}.log"
  log "pulse → $logf"
  local args=(--force)
  if [[ ${#push_args[@]} -gt 0 ]]; then
    args+=("${push_args[@]}")
  fi
  run_locked pulse "$PY" -u scripts/quant_pulse.py "${args[@]}" >>"$logf" 2>&1
}

cmd_swing_daily() {
  local logf="${LOG_DIR}/swing_daily-${TODAY_COMPACT}.log"
  log "swing_daily → $logf"
  if [[ ${#push_args[@]} -gt 0 ]]; then
    "$PY" -u scripts/swing_daily_report.py "${push_args[@]}" >>"$logf" 2>&1
  else
    "$PY" -u scripts/swing_daily_report.py >>"$logf" 2>&1
  fi
}

cmd_journal() {
  local logf="${LOG_DIR}/journal-${TODAY_COMPACT}.log"
  log "journal → $logf"
  if [[ ${#push_args[@]} -gt 0 ]]; then
    "$PY" -u scripts/trade_journal.py --db "$QUANT_DB_PATH" "${push_args[@]}" >>"$logf" 2>&1
  else
    "$PY" -u scripts/trade_journal.py --db "$QUANT_DB_PATH" >>"$logf" 2>&1
  fi
}

cmd_close() {
  local logf="${LOG_DIR}/close-${TODAY_COMPACT}.log"
  log "close → $logf"
  if [[ ${#push_args[@]} -gt 0 ]]; then
    "$PY" -u scripts/daily_close_report.py "${push_args[@]}" >>"$logf" 2>&1
  else
    "$PY" -u scripts/daily_close_report.py >>"$logf" 2>&1
  fi
}

cmd_day_close() {
  cmd_swing_daily
  cmd_journal
  cmd_close
}

usage() {
  cat <<EOF
用法: $0 <init|recalibrate|pool|pulse|swing_daily|journal|close|day_close>
环境: QUANT_DB_PATH=$QUANT_DB_PATH
      QUANT_ARTIFACT_ROOT=$QUANT_ARTIFACT_ROOT
      LINUX_SIM_PUSH=$PUSH_MODE  (1=推企微，默认0)
EOF
}

main() {
  local job="${1:-}"
  case "$job" in
    init) cmd_init ;;
    recalibrate) cmd_recalibrate ;;
    pool) cmd_pool ;;
    pulse) cmd_pulse ;;
    swing_daily) cmd_swing_daily ;;
    journal) cmd_journal ;;
    close) cmd_close ;;
    day_close) cmd_day_close ;;
    -h|--help|help|"") usage; [[ -n "$job" ]] || exit 1 ;;
    *) log "未知子命令: $job"; usage; exit 1 ;;
  esac
}

main "$@"
