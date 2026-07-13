import sqlite3
db = sqlite3.connect('data/sim_live_mirror.db')
c = db.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print([t[0] for t in c.fetchall()])
db.close()
