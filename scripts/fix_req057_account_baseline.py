"""
REQ-057 part 3 修复：account_id=1 (learn/live_mirror) 净值口径异常。

现象：initial_cash=200000 但 total_value 仅 22527.39，cumulative_return=-88.7%（垃圾值）。

根因分析（见 _req057_acct.py 输出）：
  - total_value(22527.39) = cash(13872.39) + 持仓市值(8655.00) —— 内部一致。
  - 但资金流水核对：initial(200000) - 累计buy(28784.50) + 累计sell(17694.25)
    = 188909.75 应为现金，而实际 cash 仅 13872.39。
  - 反解真实本金：cash + buy - sell = 13872.39 + 28784.50 - 17694.25 = 24962.64 ≈ 25000。
  - 即：该账户真实可用本金约 25000；config 里的 "200000（5/27 充值至 20 万）"
    从未在 DB cash 中体现（无充值流水），是错误的基线，导致 cumulative_return 失真。

修复：把 DB sim_account.initial_cash 与 config.yaml(learn) 的 initial_cash/max_total_value
     统一校准为 25000（与实际资金流水一致），使净值口径恢复正常
     (cumulative_return = 22527.39/25000 - 1 = -9.9%，符合实际)。

幂等：若已校准（initial_cash≈25000）则跳过。运行前自动备份 DB。
"""
import sqlite3, shutil, datetime, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data' / 'sim_live_mirror.db'
CORRECT_INITIAL = 25000.0
TOL = 1000.0  # 容差

def reconcile_implied(conn):
    cash = conn.execute("SELECT cash FROM sim_account WHERE id=1").fetchone()[0]
    buys = conn.execute("SELECT COALESCE(SUM(amount),0) FROM sim_trades WHERE account_id=1 AND direction='BUY'").fetchone()[0]
    sells = conn.execute("SELECT COALESCE(SUM(amount),0) FROM sim_trades WHERE account_id=1 AND direction='SELL'").fetchone()[0]
    return cash + buys - sells, cash, buys, sells

def main(apply=True):
    if not DB.exists():
        print(f"❌ DB 不存在: {DB}")
        return 1
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    acct = conn.execute("SELECT * FROM sim_account WHERE id=1").fetchone()
    if acct is None:
        print("❌ account_id=1 不存在")
        conn.close()
        return 1
    cur_initial = float(acct['initial_cash'])
    implied, cash, buys, sells = reconcile_implied(conn)
    print(f"当前 initial_cash = {cur_initial:,.2f}")
    print(f"资金流水反解本金   = cash({cash:,.2f}) + buy({buys:,.2f}) - sell({sells:,.2f}) = {implied:,.2f}")
    print(f"校准目标 initial   = {CORRECT_INITIAL:,.2f}")

    if abs(cur_initial - CORRECT_INITIAL) <= TOL:
        print("✅ 已校准（initial_cash≈25000），无需修改。")
        conn.close()
        return 0

    # 反解值应接近目标（防呆校验）
    if abs(implied - CORRECT_INITIAL) > 3000:
        print(f"⚠️ 反解本金 {implied:,.2f} 与目标 {CORRECT_INITIAL:,.2f} 偏差较大，请人工复核后再改。")
        conn.close()
        return 2

    if not apply:
        print("(dry-run) 不实际修改。")
        conn.close()
        return 0

    # 备份
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = DB.with_suffix(f'.db.req057_{ts}.bak')
    shutil.copy2(DB, bak)
    print(f"📦 已备份 DB → {bak.name}")

    total_value = float(acct['total_value'])
    conn.execute("UPDATE sim_account SET initial_cash=?, updated_at=CURRENT_TIMESTAMP WHERE id=1",
                 (CORRECT_INITIAL,))
    conn.commit()
    new_ret = (total_value / CORRECT_INITIAL - 1) * 100
    print(f"✅ 已更新 initial_cash: {cur_initial:,.2f} → {CORRECT_INITIAL:,.2f}")
    print(f"   新 cumulative_return = total_value({total_value:,.2f})/{CORRECT_INITIAL:,.0f} - 1 = {new_ret:+.2f}%")
    conn.close()
    return 0

if __name__ == '__main__':
    sys.exit(main(apply='--dry-run' not in sys.argv))
