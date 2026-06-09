"""Fix sim_account.cash for account_id=1 by recalculating from trades"""
import sqlite3
from datetime import date

conn = sqlite3.connect('data/sim_live_mirror.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

account_id = 1

# Get initial_cash
cur.execute('SELECT initial_cash FROM sim_account WHERE id=?', (account_id,))
initial_cash = float(cur.fetchone()['initial_cash'])
print(f"initial_cash: {initial_cash}")

# Calculate cash from trades
cur.execute('''
    SELECT 
        SUM(CASE WHEN direction="BUY" THEN amount + commission ELSE 0 END) as total_buy,
        SUM(CASE WHEN direction="SELL" THEN amount - commission - COALESCE(tax, 0) ELSE 0 END) as total_sell
    FROM sim_trades 
    WHERE account_id=?
''', (account_id,))
row = cur.fetchone()
total_buy = float(row['total_buy'] or 0)
total_sell = float(row['total_sell'] or 0)
print(f"total_buy (amount+commission): {total_buy:.2f}")
print(f"total_sell (amount-commission-tax): {total_sell:.2f}")

expected_cash = initial_cash - total_buy + total_sell
print(f"expected_cash: {expected_cash:.2f}")

# Update sim_account.cash
cur.execute('UPDATE sim_account SET cash=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', 
            (round(expected_cash, 2), account_id))

# Recalculate total_value
cur.execute('SELECT SUM(market_value) as total_mv FROM sim_positions WHERE account_id=? AND quantity > 0', 
            (account_id,))
row = cur.fetchone()
total_mv = float(row['total_mv'] or 0)
new_total_value = round(expected_cash + total_mv, 2)
print(f"new total_value: {new_total_value:.2f}")

# Update sim_account.total_value
cur.execute('UPDATE sim_account SET total_value=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', 
            (new_total_value, account_id))

conn.commit()

# Verify
cur.execute('SELECT cash, total_value FROM sim_account WHERE id=?', (account_id,))
row = cur.fetchone()
print(f"\nVerified: cash={row['cash']:.2f}, total_value={row['total_value']:.2f}")

conn.close()
print("\nDone!")
