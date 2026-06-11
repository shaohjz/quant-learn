"""
创建推送历史表 + 初始化买入理由数据
"""
import sqlite3
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "sim_live_mirror.db"

conn = sqlite3.connect(str(DB))

# 1. 推送历史表（存所有推送过的消息）
conn.execute("""
CREATE TABLE IF NOT EXISTS push_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    push_type TEXT NOT NULL,        -- 'advisor_pre','advisor_auction','advisor_intraday','advisor_closing','advisor_review','alert','scanner'
    phase TEXT,                     -- 阶段
    content TEXT NOT NULL,          -- 推送内容
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# 2. 持仓理由/交易逻辑表
conn.execute("""
CREATE TABLE IF NOT EXISTS position_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    stock_name TEXT,
    note_type TEXT NOT NULL,        -- 'buy_reason','sell_reason','hold_logic','target','stop_loss'
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# 3. 给现有持仓补充买入理由
notes = [
    ('002453', '华软科技', 'buy_reason', '观察列表触发buy_zone阈值，MA10回踩建仓'),
    ('002453', '华软科技', 'hold_logic', '低价股+芯片封装概念，等待板块轮动'),
    ('601728', '中国电信', 'buy_reason', '央企高股息标的，多次触发buy_zone/buy_strong分批建仓'),
    ('601728', '中国电信', 'hold_logic', '防御型持仓，股息率>4%，长期持有底仓'),
    ('600310', '广西能源', 'buy_reason', '电力板块轮动，buy_zone阈值触发(5/22@4.98)'),
    ('600310', '广西能源', 'hold_logic', '今日涨停+10%，关注止盈①(+15%=5.73)'),
    ('600130', '波导股份', 'buy_reason', '低价+手机概念异动，buy_zone触发(5/22@5.19)'),
    ('603757', '大元泵业', 'buy_reason', '盘中阈值触发自动买入(5/25@61.66)，MA10回踩'),
    ('603757', '大元泵业', 'hold_logic', '泵业龙头，近期波动大，关注止损线56.77'),
]

for code, name, ntype, content in notes:
    # 避免重复
    exists = conn.execute(
        "SELECT 1 FROM position_notes WHERE stock_code=? AND note_type=? AND content=?",
        (code, ntype, content)
    ).fetchone()
    if not exists:
        conn.execute(
            "INSERT INTO position_notes (stock_code, stock_name, note_type, content) VALUES (?,?,?,?)",
            (code, name, ntype, content)
        )

conn.commit()
print("✓ 表创建完成")
print(f"  push_history: {conn.execute('SELECT COUNT(*) FROM push_history').fetchone()[0]} 条")
print(f"  position_notes: {conn.execute('SELECT COUNT(*) FROM position_notes').fetchone()[0]} 条")
conn.close()
