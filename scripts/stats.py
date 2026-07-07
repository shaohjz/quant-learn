import sqlite3
from datetime import date

# 统计今日完成数
today = date.today().strftime('%Y-%m-%d')
conn = sqlite3.connect('data/pm.db')
c = conn.cursor()

c.execute("SELECT COUNT(*) FROM tasks WHERE DATE(updated_at) = ? AND status IN ('verified','done','fixed')", (today,))
fixed_today = c.fetchone()[0]

c.execute("SELECT COUNT(*) FROM tasks WHERE DATE(created_at) = ?", (today,))
new_today = c.fetchone()[0]

c.execute("SELECT COUNT(*) FROM tasks WHERE status = 'open'")
open_cnt = c.fetchone()[0]

c.execute("SELECT COUNT(*) FROM tasks WHERE status = 'pending'")
pending_cnt = c.fetchone()[0]

c.execute("SELECT COUNT(*) FROM tasks WHERE status = 'in_progress'")
inprog_cnt = c.fetchone()[0]

# P0 积压
c.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('open','pending','in_progress') AND (priority = 'P0' OR priority = 'high')")
p0_cnt = c.fetchone()[0]

# P1 积压
c.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('open','pending','in_progress') AND priority = 'P1'")
p1_cnt = c.fetchone()[0]

# 其他积压
c.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('open','pending','in_progress') AND priority NOT IN ('P0','P1','high')")
other_cnt = c.fetchone()[0]

conn.close()

print(f"fixed_today={fixed_today}")
print(f"new_today={new_today}")
print(f"open={open_cnt}")
print(f"pending={pending_cnt}")
print(f"in_progress={inprog_cnt}")
print(f"p0={p0_cnt}")
print(f"p1={p1_cnt}")
print(f"other={other_cnt}")
