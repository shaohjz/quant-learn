-- Migration: 001_watchlist_history
-- 创建观察池历史表（追踪自动发现股票的生命周期）
-- 日期: 2026-05-25

CREATE TABLE IF NOT EXISTS watchlist_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    category TEXT NOT NULL,  -- 'user_manual' | 'auto_discovered'
    added_at DATE NOT NULL,
    added_by TEXT,           -- 'user' | 'intraday_scanner' | 'morning_scanner' | 'ai_suggest'
    added_reason TEXT,
    discovery_score REAL,    -- 评分（仅 auto_discovered），范围 0-100
    last_alert_at DATE,      -- 最后触发告警日期
    alert_count INTEGER DEFAULT 0,
    removed_at DATE,         -- 移除日期（NULL = 仍在观察池）
    removed_reason TEXT,     -- 移除原因（inactive_N_days / trend_broken / user_delete / low_score_inactive）
    metadata TEXT,           -- JSON 存储额外元数据（tags/notes等）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(code, category, added_at)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_code ON watchlist_history(code);
CREATE INDEX IF NOT EXISTS idx_watchlist_removed ON watchlist_history(removed_at);
CREATE INDEX IF NOT EXISTS idx_watchlist_category ON watchlist_history(category);
CREATE INDEX IF NOT EXISTS idx_watchlist_last_alert ON watchlist_history(last_alert_at);

-- 触发器：自动更新 updated_at
CREATE TRIGGER IF NOT EXISTS update_watchlist_history_timestamp
AFTER UPDATE ON watchlist_history
FOR EACH ROW
BEGIN
    UPDATE watchlist_history SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
END;
