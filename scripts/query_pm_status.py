import sqlite3
import json

conn = sqlite3.connect('data/pm.db')
cursor = conn.cursor()

# Count by status
cursor.execute("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status")
status_rows = cursor.fetchall()
print("STATUS BREAKDOWN:")
for r in status_rows:
    print(f"  {r[0]}: {r[1]}")

# Count by type
cursor.execute("SELECT type, COUNT(*) as cnt FROM tasks GROUP BY type")
type_rows = cursor.fetchall()
print("\nTYPE BREAKDOWN:")
for r in type_rows:
    print(f"  {r[0]}: {r[1]}")

# In progress items
cursor.execute("SELECT id, title, priority, assigned_to FROM tasks WHERE status='in_progress' ORDER BY priority, id")
ip = cursor.fetchall()
print("\nIN_PROGRESS:")
for r in ip:
    print(f"  {r[0]} P{r[2]}: {r[1][:60]} [{r[3] or 'unassigned'}]")

# Blocked items
cursor.execute("SELECT id, title, priority FROM tasks WHERE status='blocked'")
bl = cursor.fetchall()
print("\nBLOCKED:")
for r in bl:
    print(f"  {r[0]} P{r[2]}: {r[1][:60]}")

# Open items (new/untriaged)
cursor.execute("SELECT id, title, priority, type FROM tasks WHERE status='open' ORDER BY priority, id")
op = cursor.fetchall()
print("\nOPEN (new/needs triage):")
for r in op:
    print(f"  {r[0]} P{r[2]} ({r[3]}): {r[1][:60]}")

# testing/fixed items
cursor.execute("SELECT id, title, priority, status FROM tasks WHERE status IN ('testing','fixed','verified') ORDER BY status, priority")
tf = cursor.fetchall()
print("\nTESTING/FIXED/VERIFIED:")
for r in tf:
    print(f"  {r[0]} [{r[3]}] P{r[2]}: {r[1][:60]}")

conn.close()
