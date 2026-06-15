#!/usr/bin/env python3
"""
sync_live.py - 将真实持仓同步到 sim.db（模拟盘数据库）
用法: python scripts/sync_live.py
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

SIM_DB = DATA / "sim.db"
REAL_JSON = DATA / "real_holdings.json"


def load_real_holdings():
    """加载真实持仓JSON，支持两种格式：
    - 格式A（旧）：直接是数组 [...]
    - 格式B（新）：{ "holdings": [...] }
    """
    if not REAL_JSON.exists():
        print(f"[WARN] {REAL_JSON} not found, using empty holdings")
        return []
    with open(REAL_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        holdings = data
    elif isinstance(data, dict) and "holdings" in data:
        holdings = data["holdings"]
    else:
        print(f"[ERR] Unknown format in {REAL_JSON}")
        return []
    print(f"[INFO] Loaded {len(holdings)} holdings from {REAL_JSON.name}")
    return holdings


def get_latest_price_from_csv(stock_code: str) -> float | None:
    """从本地CSV文件读取最新收盘价"""
    # 尝试不同路径
    csv_path = DATA / f"{stock_code}.csv"
    if not csv_path.exists():
        # 也尝试加.BAK?
        print(f"  [WARN] CSV not found for {stock_code}")
        return None
    try:
        conn = sqlite3.connect(":memory:")
        cur = conn.cursor()
        # 用csv模块手动读最后一行更快
        import csv
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            return None
        last_row = rows[-1]
        price = float(last_row.get("close", 0))
        trade_date = last_row.get("date", "unknown")
        print(f"  {stock_code}: latest close={price} @ {trade_date}")
        return price
    except Exception as e:
        print(f"  [ERR] reading CSV for {stock_code}: {e}")
        return None


def get_latest_price_from_akshare(stock_code: str) -> float | None:
    """用akshare获取实时价格（备用）"""
    try:
        import akshare as ak
        # 判断市场
        if stock_code.startswith("6"):
            market = "sh"
        else:
            market = "sz"
        df = ak.stock_zh_a_spot_em()
        row = df[df['代码'] == stock_code]
        if not row.empty:
            price = float(row.iloc[0]['最新价'])
            print(f"  {stock_code}: akshare price={price}")
            return price
    except Exception as e:
        print(f"  [ERR] akshare for {stock_code}: {e}")
    return None


def sync():
    """主同步逻辑"""
    holdings = load_real_holdings()
    if not holdings:
        print("[WARN] No holdings to sync, skipping")
        return

    conn = sqlite3.connect(str(SIM_DB))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 确保 account 存在
    cur.execute("SELECT id FROM sim_account WHERE account_name='default'")
    row = cur.fetchone()
    if row:
        account_id = row["id"]
        print(f"[INFO] Using existing account id={account_id}")
    else:
        cur.execute(
            "INSERT INTO sim_account (account_name, initial_cash, cash, total_value) VALUES (?, ?, ?, ?)",
            ("default", 10000.0, 10000.0, 10000.0),
        )
        account_id = cur.lastrowid
        print(f"[INFO] Created new account id={account_id}")

    # 清空旧持仓（同步场景：用真实持仓覆盖）
    cur.execute("DELETE FROM sim_positions WHERE account_id=?", (account_id,))
    print(f"[INFO] Cleared old positions for account {account_id}")

    total_market_value = 0.0

    for h in holdings:
        code = h["code"]
        name = h.get("name", code)
        qty = int(h["qty"])
        cost = float(h["cost"])
        # 优先用 JSON 里的 current，若为 null/0 则读 CSV，再失败用 cost
        current = h.get("current", None)
        if current is not None and current > 0:
            current = float(current)
        else:
            csv_price = get_latest_price_from_csv(code)
            if csv_price:
                current = csv_price
            else:
                current = cost
                print(f"  [WARN] {code} price unavailable, using cost={cost:.2f}")

        market_value = qty * current
        pnl = (current - cost) * qty
        pnl_pct = (current - cost) / cost if cost else 0

        total_market_value += market_value

        # 检查止损/止盈规则
        rules = h.get("rules", [])
        alerts = []
        for rule in rules:
            trigger = rule.get("trigger", 0)
            level = rule.get("level", "")
            dir_ = rule.get("dir", "below")
            if dir_ == "below" and current <= trigger:
                alerts.append(f"[ALERT] {level} TRIGGERED: {code} current={current:.2f} <= trigger={trigger:.2f}")
            elif dir_ == "above" and current >= trigger:
                alerts.append(f"[ALERT] {level} TRIGGERED: {code} current={current:.2f} >= trigger={trigger:.2f}")

        for alert in alerts:
            print(alert)

        cur.execute(
            """
            INSERT INTO sim_positions
            (account_id, stock_code, stock_name, quantity, avg_cost, current_price,
             market_value, pnl, pnl_pct, trailing_stop_price, highest_price, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                code,
                name,
                qty,
                cost,
                current,
                market_value,
                pnl,
                pnl_pct,
                None,  # trailing_stop_price
                current,  # highest_price init to current
                datetime.now().isoformat(),
            ),
        )
        print(f"[SYNC] {code}({name}): qty={qty}, cost={cost:.2f}, current={current:.2f}, "
              f"market_value={market_value:.0f}, pnl={pnl:+.0f}({pnl_pct:+.1%})")

    # 更新 account：计算剩余现金和总市值
    # 真实场景：cash 应从券商API获取
    # 这里用 simplified 逻辑：
    #   假设初始资金 = 10000，买入持仓花掉的资金 = sum(qty * cost)
    #   现金 = initial_cash - sum(买入成本)
    # 但更简单：直接用 JSON 里的 cash 字段（如果存在），否则用 initial_cash
    cur.execute("SELECT initial_cash FROM sim_account WHERE id=?", (account_id,))
    initial_cash = cur.fetchone()["initial_cash"]
    # 计算已投入成本
    total_cost = sum(h.get('qty', 0) * float(h.get('cost', 0)) for h in holdings)
    cash = initial_cash - total_cost  # 简化：假设用初始资金买入
    total_value = cash + total_market_value
    cur.execute(
        "UPDATE sim_account SET cash=?, total_value=?, updated_at=? WHERE id=?",
        (cash, total_value, datetime.now().isoformat(), account_id),
    )

    conn.commit()
    conn.close()
    print(f"\n[INFO] Sync complete. Total market value: {total_market_value:.0f}, Total account value: {total_value:.0f}")


if __name__ == "__main__":
    sync()
