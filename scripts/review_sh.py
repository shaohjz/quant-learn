# -*- coding: utf-8 -*-
import sqlite3, json
conn = sqlite3.connect(r"C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db")
c = conn.cursor()
with open(r"C:\Users\Administrator\.openclaw\workspace\quant-learn\output\news_signals_2026-07-17.json", encoding="utf-8") as f:
    data = json.load(f)
titles = {s["id"]: s["title"] for s in data["signals"]}
c.execute("SELECT id, stock_code, signal_action, signal_reason FROM strategy_shadow_signals WHERE shadow_date='2026-07-17' AND signal_action IN ('SELL','HOLD') ORDER BY signal_action, id")
for r in c.fetchall():
    print(r[0], r[1], r[2], "|", r[3], "|", titles.get(r[0], "?"))
conn.close()
