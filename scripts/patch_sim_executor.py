"""Patch sim_executor.py: 插入 REQ-038 持仓数量硬上限检查"""
import re

path = 'scripts/sim_executor.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# ── 1. 在 COMMISSION_RATE 常量后插入风控常量加载 ──────────────────
old_const = """# 费率
COMMISSION_RATE = 0.00025   # 万2.5
STAMP_TAX_RATE = 0.0005   # 万5（仅卖出）"""
new_const = """# 费率
COMMISSION_RATE = 0.00025   # 万2.5
STAMP_TAX_RATE = 0.0005   # 万5（仅卖出）

# ── REQ-038 持仓数量硬上限（从 config.yaml 读取，缺省 6/2）─────────────────────
def _load_risk_limits():
    \"\"\"从 config.yaml 读取风控上限，返回 (max_total, max_daily_new).\"\"\"
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
        risk = cfg.get('risk') or {}
        max_total = int(risk.get('max_total_positions', 6))
        max_daily = int(risk.get('max_daily_new_positions', 2))
        return max_total, max_daily
    except Exception:
        return 6, 2

MAX_TOTAL_POSITIONS, MAX_DAILY_NEW_POSITIONS = _load_risk_limits()"""
if old_const in content:
    content = content.replace(old_const, new_const, 1)
    print('[OK] 风控常量已插入')
else:
    print('[WARN] 未找到常量插入点，跳过')

# ── 2. 在 decide_action() 的 `return "BUY"` 前插入硬上限检查 ─────────
old_buy = """        finally:
            conn.close()

        return 'BUY'"""
new_buy = """        finally:
            conn.close()

        # ── REQ-038 持仓数量硬上限检查 ─────────────────────────────────────
        # 1) 总持仓数上限
        conn = sqlite3.connect(_DB_PATH)
        try:
            total_pos = conn.execute(
                "SELECT COUNT(*) FROM sim_positions WHERE account_id=? AND quantity > 0",
                (_ACCOUNT_ID,)
            ).fetchone()[0]
        finally:
            conn.close()
        if total_pos >= MAX_TOTAL_POSITIONS:
            reason = f'总持仓数({total_pos})≥上限({MAX_TOTAL_POSITIONS})，拒绝新建 {code}'
            logger.info(f'🚫 [{code}] {reason}')
            _write_review_decision(_ACCOUNT_ID, code, 'position_count_limit', 0, reason)
            return 'NO_ACTION'

        # 2) 单日新建仓位数上限（只限制"新买入"，已有仓位加仓不受影响）
        conn = sqlite3.connect(_DB_PATH)
        try:
            # 检查是否已有持仓
            existing = conn.execute(
                "SELECT quantity FROM sim_positions WHERE account_id=? AND stock_code=? AND quantity > 0",
                (_ACCOUNT_ID, code)
            ).fetchone()
            if not existing:
                # 是新建仓位，检查今日已新建数量
                from datetime import datetime
                today = datetime.now().strftime('%Y-%m-%d')
                new_today = conn.execute(
                    "SELECT COUNT(DISTINCT stock_code) FROM sim_trades "
                    "WHERE account_id=? AND direction='BUY' AND trade_date=?",
                    (_ACCOUNT_ID, today)
                ).fetchone()[0]
                if new_today >= MAX_DAILY_NEW_POSITIONS:
                    reason = f'今日新建仓位({new_today})≥上限({MAX_DAILY_NEW_POSITIONS})，拒绝新建 {code}'
                    logger.info(f'🚫 [{code}] {reason}')
                    _write_review_decision(_ACCOUNT_ID, code, 'daily_new_position_limit', 0, reason)
                    return 'NO_ACTION'
        finally:
            conn.close()

        _write_review_decision(_ACCOUNT_ID, code, 'buy', 1, f'{level} 信号通过风控')
        return 'BUY'"""
if old_buy in content:
    content = content.replace(old_buy, new_buy, 1)
    print('[OK] decide_action() 硬上限检查已插入')
else:
    print('[ERROR] 未找到 return BUY 插入点！')
    # 调试：打印附近内容
    idx = content.find("return 'BUY'")
    if idx >= 0:
        print('  附近内容:', repr(content[max(0,idx-200):idx+50]))

# ── 3. 添加 _write_review_decision() 辅助函数 ─────────────────────
# 在 decide_action 函数定义之前插入（在文件靠前位置，_load_risk_limits 之后）
helper_fn = '''
def _write_review_decision(account_id: int, stock_code: str, decision_type: str,
                           allowed: int, reason: str):
    """写入 review_decisions 表留痕（表不存在时静默失败）。"""
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS review_decisions ("
            "  id              INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  account_id      INTEGER NOT NULL,"
            "  stock_code      TEXT    NOT NULL,"
            "  trade_date      DATE    NOT NULL DEFAULT (date('now', 'localtime')),"
            "  decision_type   TEXT    NOT NULL,"
            "  allowed         INTEGER NOT NULL,"
            "  reason          TEXT,"
            "  created_at      TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))"
            ")"
        )
        conn.execute(
            "INSERT INTO review_decisions (account_id, stock_code, decision_type, allowed, reason) "
            "VALUES (?, ?, ?, ?, ?)",
            (account_id, stock_code, decision_type, allowed, reason)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"_write_review_decision 失败: {e}")
'''
# 插入位置：在 MAX_TOTAL_POSITIONS 赋值行之后
insert_marker = 'MAX_TOTAL_POSITIONS, MAX_DAILY_NEW_POSITIONS = _load_risk_limits()'
if insert_marker in content and '_write_review_decision' not in content:
    content = content.replace(insert_marker, insert_marker + helper_fn, 1)
    print('[OK] _write_review_decision() 已插入')
else:
    print('[WARN] _write_review_decision 已存在或找不到插入点')

# 写回
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print('\\n✅ Patch 完成，正在语法检查...')
import ast, sys
try:
    ast.parse(content)
    print('✅ 语法检查通过')
except SyntaxError as e:
    print(f'❌ 语法错误: {e}')
    sys.exit(1)
