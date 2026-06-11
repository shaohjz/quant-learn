"""REQ-056 strategy control dashboard API tests."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _init_sim_db(path: Path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE sim_account (
                id INTEGER PRIMARY KEY,
                account_name TEXT,
                initial_cash REAL,
                cash REAL,
                total_value REAL,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE sim_positions (
                id INTEGER PRIMARY KEY,
                account_id INTEGER,
                stock_code TEXT,
                stock_name TEXT,
                quantity INTEGER,
                avg_cost REAL,
                current_price REAL,
                market_value REAL,
                pnl REAL,
                pnl_pct REAL,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE sim_trades (
                id INTEGER PRIMARY KEY,
                account_id INTEGER,
                trade_date TEXT,
                trade_time TEXT,
                stock_code TEXT,
                stock_name TEXT,
                direction TEXT,
                price REAL,
                quantity INTEGER,
                amount REAL,
                signal_reason TEXT,
                trade_context TEXT,
                signal_detail TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE sim_orders (
                id INTEGER PRIMARY KEY,
                account_id INTEGER,
                order_time TEXT,
                stock_code TEXT,
                stock_name TEXT,
                direction TEXT,
                quantity INTEGER,
                price REAL,
                status TEXT,
                strategy_name TEXT,
                signal_reason TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute("INSERT INTO sim_account VALUES (1,'learn',200000,150000,200000,'','')")
        conn.execute("INSERT INTO sim_positions (account_id,stock_code,stock_name,quantity,avg_cost,current_price,market_value,pnl,pnl_pct) VALUES (1,'002156','通富微电',100,50,60,6000,1000,0.2)")
        conn.execute("INSERT INTO sim_trades (account_id,trade_date,trade_time,stock_code,stock_name,direction,price,quantity,amount,signal_reason,trade_context,signal_detail,created_at) VALUES (1,'2026-06-01','09:35:00','002156','通富微电','BUY',60,100,6000,'强买区触发','{}','{}','2026-06-01 09:35:00')")
        conn.execute("INSERT INTO sim_orders (account_id,order_time,stock_code,stock_name,direction,quantity,price,status,strategy_name,signal_reason,created_at) VALUES (1,'2026-06-01 09:35:00','002156','通富微电','BUY',100,60,'filled','fusion','强买区触发','2026-06-01 09:35:00')")
        conn.commit()


def test_strategy_control_api_returns_rules_and_recent_hits(tmp_path):
    from web.app import app

    db_path = tmp_path / "sim.db"
    cfg_path = tmp_path / "config.yaml"
    _init_sim_db(db_path)
    cfg_path.write_text(
        """
accounts:
  learn:
    initial_cash: 200000
    auto_trade: true
    max_total_value: 200000
risk:
  max_position_pct: 0.2
  max_total_positions: 6
  max_daily_new_positions: 3
  max_daily_trades: 10
  max_daily_build_amount_pct: 0.3
  stop_loss_pct: -0.08
  take_profit_pct: 0.15
real_portfolio_rules:
  '002156':
    name: 通富微电
    rules:
      stop_loss:
        trigger: 55
        dir: below
        msg: 跌破止损
      take_profit:
        trigger: 70
        dir: above
        msg: 突破止盈
watchlist:
  user_manual:
    '002156':
      name: 通富微电
      enabled: true
      source: 测试
      added_reason: 单测
      rules:
        buy_zone:
          trigger: 60
          dir: below
          msg: 回踩买入
""".strip(),
        encoding="utf-8",
    )
    app.config["TESTING"] = True
    app.config["SIM_DB_PATH"] = str(db_path)
    app.config["CONFIG_PATH"] = str(cfg_path)

    with app.test_client() as client:
        res = client.get("/api/strategy_control")
        assert res.status_code == 200, res.get_data(as_text=True)
        body = res.get_json()
        assert body["position_controls"]["auto_trade"] is True
        assert body["position_controls"]["max_position_pct"] == 20.0
        assert body["position_controls"]["today_new_positions"] == 1
        assert body["cash_level"]["cash_pct"] > 90
        assert body["buy_rules"]["watchlist_count"] == 1
        assert "回踩买入" in body["buy_rules"]["sample_rules"][0]["trigger_rules"][0]
        assert body["sell_rules"]["global_stop_loss_pct"] == -8.0
        assert body["recent_hits"]["trades"][0]["signal_reason"] == "强买区触发"
