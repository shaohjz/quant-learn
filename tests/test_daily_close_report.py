"""收盘日报：当日盈亏必须相对昨日净值，禁止写死 10 万。"""

import sqlite3
from pathlib import Path

from scripts.daily_close_report import account_block, build_report, load_swing_snippet


def _db(tmp: Path) -> Path:
    db = tmp / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE sim_account (
            id INTEGER PRIMARY KEY, account_name TEXT,
            cash REAL, total_value REAL, initial_cash REAL
        );
        CREATE TABLE sim_trades (
            id INTEGER PRIMARY KEY, account_id INT, trade_date TEXT, trade_time TEXT,
            stock_code TEXT, stock_name TEXT, direction TEXT,
            price REAL, quantity INT, amount REAL, signal_reason TEXT
        );
        CREATE TABLE sim_positions (
            account_id INT, stock_code TEXT, stock_name TEXT, quantity INT,
            avg_cost REAL, current_price REAL, market_value REAL, pnl REAL, pnl_pct REAL
        );
        CREATE TABLE sim_daily_nav (
            account_id INT, trade_date TEXT, total_value REAL,
            PRIMARY KEY (account_id, trade_date)
        );
        """
    )
    conn.execute(
        "INSERT INTO sim_account VALUES (1,'learn',121992,219479.43,200000)"
    )
    conn.execute("INSERT INTO sim_daily_nav VALUES (1,'2026-07-14',219360.0)")
    conn.execute(
        "INSERT INTO sim_account VALUES (3,'swing_trade',100000,100000,100000)"
    )
    conn.execute("INSERT INTO sim_daily_nav VALUES (3,'2026-07-14',100000)")
    conn.commit()
    conn.close()
    return db


def test_day_pnl_not_vs_100k(tmp_path):
    db = _db(tmp_path)
    conn = sqlite3.connect(db)
    b = account_block(conn, 1, "模拟学习仓", "2026-07-15")
    conn.close()
    assert b["day_pnl"] is not None
    assert abs(b["day_pnl"] - 119.43) < 0.01
    assert abs(b["day_pct"]) < 1.0
    assert abs(b["cum_pnl"] - 19479.43) < 0.01


def test_report_mentions_both_accounts(tmp_path, monkeypatch):
    import scripts.daily_close_report as mod

    db = _db(tmp_path)
    monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "output")
    (tmp_path / "output" / "swing_daily").mkdir(parents=True)
    md = build_report("2026-07-15", db_path=db)
    assert "模拟学习仓" in md
    assert "波段" in md
    assert "**今日 +119.43（+0.05%）**" in md
    assert "总资产 219,479.43（较昨日 +119.43）" in md
    assert "+119,479" not in md
    assert "波段操作" in md
    assert "今日=相对昨日净值；累计=相对期初资金" in md
    assert "可用现金" not in md
    assert "建仓归因" not in md


def test_report_warns_when_swing_day_and_cumulative_have_opposite_signs(
    tmp_path, monkeypatch
):
    import scripts.daily_close_report as mod

    db = _db(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE sim_account SET cash=50247,total_value=50247,initial_cash=50000 "
        "WHERE id=3"
    )
    conn.execute("UPDATE sim_daily_nav SET total_value=50553 WHERE account_id=3")
    conn.commit()
    conn.close()

    monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "output")
    (tmp_path / "output" / "swing_daily").mkdir(parents=True)
    md = build_report("2026-07-15", db_path=db)
    assert "**今日 -306.00（-0.61%）**" in md
    assert "总资产 50,247.00（较昨日 -306.00）" in md
    assert "别混淆：波段今天亏 ¥306.00；累计仍赚 ¥247.00" in md


def test_swing_snippet_keeps_only_real_advice(tmp_path, monkeypatch):
    import scripts.daily_close_report as mod

    monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path)
    out = tmp_path / "swing_daily"
    out.mkdir()
    (out / "2026-07-15.md").write_text(
        "# 波段结论\n"
        "## 🟢 波段模拟今日赚 ¥221\n"
        "## 给你挂单建议（实盘参考）\n"
        "- **WATCH_BUY 海康威视(002415)** @ 35.41\n"
        "## 波段模拟持仓\n"
        "- 东方财富 +1%\n",
        encoding="utf-8",
    )
    snippet = load_swing_snippet("2026-07-15")
    assert snippet == "- **WATCH_BUY 海康威视(002415)** @ 35.41"
    assert "波段模拟今日赚" not in snippet
    assert "东方财富" not in snippet
