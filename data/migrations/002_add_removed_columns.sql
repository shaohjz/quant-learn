-- Migration: 002_add_removed_columns
-- 为 watchlist_history 表添加 removed_at 和 removed_reason 列
-- 这些列在原始 schema（001_watchlist_history.sql）中已定义，
-- 但 init_watchlist_table.py 创建的简化版表缺少它们，
-- 导致 sim/portfolio.py 和 scripts/cleanup_watchlist.py 中的查询失败。
-- 日期: 2026-07-20

-- 幂等添加 removed_at 列
ALTER TABLE watchlist_history ADD COLUMN removed_at TEXT;

-- 幂等添加 removed_reason 列
ALTER TABLE watchlist_history ADD COLUMN removed_reason TEXT;
