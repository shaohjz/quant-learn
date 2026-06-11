"""给电信的买入规则上保险栓 + 给 live_mirror 充 10 万"""
import sqlite3
import yaml
from datetime import datetime
from pathlib import Path

PROJECT = Path(r'C:\Users\Administrator\.openclaw\workspace\quant-learn')
CONFIG = PROJECT / 'config.yaml'
DB = PROJECT / 'data' / 'sim_live_mirror.db'

# ============ 1) 修改电信规则：暂停自动买入 ============
print('=== Step 1: 冻结 601728 中国电信 自动买入 ===')
cfg = yaml.safe_load(CONFIG.read_text(encoding='utf-8'))
dx = cfg['watchlist']['user_manual']['601728']
old_rules = dx.get('rules', {})
print(f'  Before: enabled={dx.get("enabled")}, rules={list(old_rules.keys())}')

# 备份原阈值进 notes，移除 buy_zone/buy_strong，添加 trend_break_warn 仅观察
backup_rules = {k: v for k, v in old_rules.items()}
dx['rules_backup_2026-05-27'] = backup_rules
dx['enabled'] = True  # 仍然在监控池里，只是不让自动下单
dx['auto_buy_disabled'] = True  # 标记位
dx['auto_buy_disabled_reason'] = '5/27: 趋势未企稳(MA20下方震荡)，暂停自动建仓，等右侧确认后人工恢复'
dx['auto_buy_disabled_at'] = '2026-05-27'

# 用 trend_watch（仅观察，executor 不会触发买入）替代 buy_zone/buy_strong
dx['rules'] = {
    'trend_watch': {
        'trigger': 5.96,
        'dir': 'below',
        'msg': '⚠️ 中国电信跌破 5.96 (MA60关键支撑)！趋势恐实质性走坏，仅警示',
    },
    'right_side_confirm': {
        'trigger': 6.30,
        'dir': 'above',
        'msg': '✅ 中国电信站上 6.30 (MA20上方有效)！可考虑解除自动买入冻结',
    },
}
print(f'  After:  enabled={dx["enabled"]}, auto_buy_disabled=True, rules={list(dx["rules"].keys())}')

CONFIG.write_text(
    yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False),
    encoding='utf-8'
)
print('  config.yaml 已更新')

# ============ 2) 学习账户充 10 万 ============
print('\n=== Step 2: live_mirror 账户充值 ¥100,000 ===')
conn = sqlite3.connect(DB)
cur = conn.cursor()

# 当前
row = cur.execute("SELECT id, cash, total_value FROM sim_account WHERE id=1").fetchone()
print(f'  Before: id=1 live_mirror  cash=¥{row[1]:,.2f}  total=¥{row[2]:,.2f}')

# 充值
new_cash = row[1] + 100000.0
new_total = row[2] + 100000.0
cur.execute(
    "UPDATE sim_account SET cash=?, total_value=?, updated_at=? WHERE id=1",
    (new_cash, new_total, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
)

# 记一笔流水（伪 BUY 不行，用单独表？看了 sim_trades 字段没有 deposit 类型，直接写在 review_reflections 留痕）
# 先看下 sim_daily_nav 记录
print('  注入完成')

row = cur.execute("SELECT id, cash, total_value FROM sim_account WHERE id=1").fetchone()
print(f'  After:  id=1 live_mirror  cash=¥{row[1]:,.2f}  total=¥{row[2]:,.2f}')

conn.commit()
conn.close()

print('\n=== Done ===')
