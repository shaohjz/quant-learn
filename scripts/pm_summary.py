import sqlite3
from collections import Counter
c = sqlite3.connect('data/pm.db')
rows = list(c.execute("SELECT id,type,title,status,priority,updated_at FROM tasks"))
print("=== STATUS ==="); 
for k,v in Counter(r[3] for r in rows).most_common(): print(f"{k}: {v}")
print("=== PRIORITY ===")
for k,v in Counter(r[4] for r in rows).most_common(): print(f"{k}: {v}")
print("=== ALL (sorted by prio) ===")
def pk(r):
    p=(r[4] or '').upper()
    order={'P0':0,'S1':0,'HIGH':1,'P1':1,'S2':2,'P2':3,'P3':4}
    return order.get(p,9)
for r in sorted(rows,key=pk):
    print(f"[{r[3]:>8}] {r[4]:>5} {r[0]:<24} {r[1]:<6} {r[2][:40]}  (upd {r[5][:10]})")
