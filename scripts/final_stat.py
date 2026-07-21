# -*- coding: utf-8 -*-
import sqlite3
conn = sqlite3.connect(r"C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db")
c = conn.cursor()
c.execute("SELECT signal_action, COUNT(*) FROM strategy_shadow_signals WHERE shadow_date='2026-07-17' GROUP BY signal_action")
d = dict(c.fetchall())
conn.close()
b = d.get("BUY", 0); s = d.get("SELL", 0); h = d.get("HOLD", 0)
print("BUY", b, "SELL", s, "HOLD", h, "TOTAL", b + s + h)
print("SUMMARY|%d|%d|%d" % (b, s, h))
