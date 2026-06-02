import sqlite3
con=sqlite3.connect('data/pm.db')
print(con.execute("select count(*) from tasks where status='pending'").fetchone()[0])
con.close()
