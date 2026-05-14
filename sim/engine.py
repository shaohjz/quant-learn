"""
sim/engine.py
模拟交易引擎 — 管理模拟账户、持仓、交易记录
"""

import math
from datetime import date as Date
from decimal import Decimal
from sim.db import get_conn


# 费用常量
COMMISSION_RATE = 0.0003   # 佣金万3
MIN_COMMISSION = 5.0       # 最低佣金5元
STAMP_TAX_RATE = 0.001     # 印花税千1（仅卖出）


class SimEngine:
    """模拟交易引擎"""

    def __init__(self, account_id: int = 1):
        self.account_id = account_id

    # ---------- 账户 ----------
    def get_account(self) -> dict:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, account_name, initial_cash, cash, total_value, updated_at "
                    "FROM sim_account WHERE id = %s",
                    (self.account_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"账户 {self.account_id} 不存在")
                return {
                    "id": row[0],
                    "account_name": row[1],
                    "initial_cash": float(row[2]),
                    "cash": float(row[3]),
                    "total_value": float(row[4]),
                    "updated_at": row[5],
                }
        finally:
            conn.close()

    def _update_cash(self, new_cash: float):
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sim_account SET cash = %s WHERE id = %s",
                    (round(new_cash, 2), self.account_id),
                )
        finally:
            conn.close()

    # ---------- 持仓 ----------
    def get_positions(self) -> list:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, stock_code, stock_name, quantity, avg_cost, "
                    "current_price, market_value, pnl, pnl_pct "
                    "FROM sim_positions WHERE account_id = %s AND quantity > 0",
                    (self.account_id,),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            conn.close()

    def _get_position(self, stock_code: str) -> dict | None:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, quantity, avg_cost FROM sim_positions "
                    "WHERE account_id = %s AND stock_code = %s AND quantity > 0",
                    (self.account_id, stock_code),
                )
                row = cur.fetchone()
                if row:
                    return {"id": row[0], "quantity": row[1], "avg_cost": float(row[2])}
                return None
        finally:
            conn.close()

    # ---------- 买入 ----------
    def buy(self, stock_code: str, price: float, quantity: int,
            stock_name: str = "", signal_reason: str = "",
            trade_date: Date = None) -> dict:
        """
        买入（佣金万3，最低5元）
        返回 {success, msg, amount, commission}
        """
        if quantity <= 0 or price <= 0:
            return {"success": False, "msg": "价格/数量无效"}

        # 数量向下取整到100股
        quantity = (quantity // 100) * 100
        if quantity == 0:
            return {"success": False, "msg": "数量不足100股"}

        amount = price * quantity
        commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
        total_cost = amount + commission

        acct = self.get_account()
        if total_cost > acct["cash"]:
            return {"success": False, "msg": f"资金不足（需 {total_cost:.2f}, 可用 {acct['cash']:.2f}）"}

        trade_date = trade_date or Date.today()
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                # 1. 扣减现金
                new_cash = acct["cash"] - total_cost
                cur.execute("UPDATE sim_account SET cash = %s WHERE id = %s",
                            (round(new_cash, 2), self.account_id))

                # 2. 更新持仓（合并/新建）
                pos = self._get_position(stock_code)
                if pos:
                    # 合并持仓
                    old_qty = pos["quantity"]
                    old_cost = pos["avg_cost"]
                    new_qty = old_qty + quantity
                    new_avg = (old_cost * old_qty + price * quantity) / new_qty
                    cur.execute(
                        "UPDATE sim_positions SET quantity = %s, avg_cost = %s, "
                        "current_price = %s, market_value = %s, "
                        "pnl = %s, pnl_pct = %s "
                        "WHERE id = %s",
                        (new_qty, round(new_avg, 4), price,
                         round(price * new_qty, 2),
                         round((price - new_avg) * new_qty, 2),
                         round((price - new_avg) / new_avg, 4) if new_avg else 0,
                         pos["id"]),
                    )
                else:
                    cur.execute(
                        "INSERT INTO sim_positions "
                        "(account_id, stock_code, stock_name, quantity, avg_cost, "
                        "current_price, market_value, pnl, pnl_pct) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (self.account_id, stock_code, stock_name, quantity,
                         round(price, 4), round(price, 4),
                         round(price * quantity, 2), 0, 0),
                    )

                # 3. 写交易记录
                cur.execute(
                    "INSERT INTO sim_trades "
                    "(account_id, trade_date, stock_code, stock_name, direction, "
                    "price, quantity, amount, commission, tax, signal_reason) "
                    "VALUES (%s, %s, %s, %s, 'BUY', %s, %s, %s, %s, 0, %s)",
                    (self.account_id, trade_date, stock_code, stock_name,
                     round(price, 4), quantity, round(amount, 2),
                     round(commission, 2), signal_reason),
                )
        finally:
            conn.close()

        return {
            "success": True,
            "msg": f"买入 {stock_name or stock_code} {quantity}股 @ {price:.4f}",
            "amount": round(amount, 2),
            "commission": round(commission, 2),
        }

    # ---------- 卖出 ----------
    def sell(self, stock_code: str, price: float, quantity: int,
             stock_name: str = "", signal_reason: str = "",
             trade_date: Date = None) -> dict:
        """
        卖出（佣金万3最低5元 + 印花税千1）
        """
        if quantity <= 0 or price <= 0:
            return {"success": False, "msg": "价格/数量无效"}

        pos = self._get_position(stock_code)
        if not pos:
            return {"success": False, "msg": f"{stock_code} 无持仓"}
        if quantity > pos["quantity"]:
            return {"success": False, "msg": f"卖出数量 {quantity} > 持仓 {pos['quantity']}"}

        amount = price * quantity
        commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
        tax = amount * STAMP_TAX_RATE
        net_income = amount - commission - tax

        trade_date = trade_date or Date.today()
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                # 1. 增加现金
                acct = self.get_account()
                new_cash = acct["cash"] + net_income
                cur.execute("UPDATE sim_account SET cash = %s WHERE id = %s",
                            (round(new_cash, 2), self.account_id))

                # 2. 更新持仓
                remain = pos["quantity"] - quantity
                if remain > 0:
                    cur.execute(
                        "UPDATE sim_positions SET quantity = %s, "
                        "current_price = %s, market_value = %s, "
                        "pnl = %s, pnl_pct = %s "
                        "WHERE id = %s",
                        (remain, price, round(price * remain, 2),
                         round((price - pos["avg_cost"]) * remain, 2),
                         round((price - pos["avg_cost"]) / pos["avg_cost"], 4)
                         if pos["avg_cost"] else 0,
                         pos["id"]),
                    )
                else:
                    cur.execute(
                        "UPDATE sim_positions SET quantity = 0, market_value = 0, "
                        "pnl = 0, pnl_pct = 0 WHERE id = %s",
                        (pos["id"],),
                    )

                # 3. 写交易记录
                cur.execute(
                    "INSERT INTO sim_trades "
                    "(account_id, trade_date, stock_code, stock_name, direction, "
                    "price, quantity, amount, commission, tax, signal_reason) "
                    "VALUES (%s, %s, %s, %s, 'SELL', %s, %s, %s, %s, %s, %s)",
                    (self.account_id, trade_date, stock_code, stock_name,
                     round(price, 4), quantity, round(amount, 2),
                     round(commission, 2), round(tax, 2), signal_reason),
                )
        finally:
            conn.close()

        return {
            "success": True,
            "msg": f"卖出 {stock_name or stock_code} {quantity}股 @ {price:.4f}",
            "amount": round(amount, 2),
            "commission": round(commission, 2),
            "tax": round(tax, 2),
        }

    # ---------- 更新持仓价格 ----------
    def update_prices(self, price_dict: dict):
        """
        price_dict: {stock_code: latest_price}
        更新持仓现价、市值、盈亏
        """
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                for code, p in price_dict.items():
                    cur.execute(
                        "UPDATE sim_positions SET "
                        "current_price = %s, "
                        "market_value = quantity * %s, "
                        "pnl = (quantity * %s) - (quantity * avg_cost), "
                        "pnl_pct = CASE WHEN avg_cost > 0 THEN (%s - avg_cost) / avg_cost ELSE 0 END "
                        "WHERE account_id = %s AND stock_code = %s AND quantity > 0",
                        (p, p, p, p, self.account_id, code),
                    )
        finally:
            conn.close()

    # ---------- 每日结算 ----------
    def daily_settle(self, trade_date: Date = None):
        """
        每日结算：刷新总资产、记录净值
        """
        trade_date = trade_date or Date.today()
        acct = self.get_account()
        positions = self.get_positions()

        market_value = sum(float(p["market_value"] or 0) for p in positions)
        total_value = acct["cash"] + market_value

        # 更新账户总资产
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sim_account SET total_value = %s WHERE id = %s",
                    (round(total_value, 2), self.account_id),
                )

                # 计算日收益率和累计收益率
                initial_cash = acct["initial_cash"]
                cumulative_return = (total_value - initial_cash) / initial_cash if initial_cash else 0

                # 获取前一交易日净值计算日收益
                cur.execute(
                    "SELECT total_value FROM sim_daily_nav "
                    "WHERE account_id = %s AND trade_date < %s "
                    "ORDER BY trade_date DESC LIMIT 1",
                    (self.account_id, trade_date),
                )
                prev = cur.fetchone()
                prev_value = float(prev[0]) if prev else initial_cash
                daily_return = (total_value - prev_value) / prev_value if prev_value else 0

                # 计算最大回撤
                cur.execute(
                    "SELECT MAX(total_value) FROM sim_daily_nav WHERE account_id = %s",
                    (self.account_id,),
                )
                peak_row = cur.fetchone()
                peak = float(peak_row[0]) if peak_row and peak_row[0] else initial_cash
                peak = max(peak, total_value)
                max_drawdown = (peak - total_value) / peak if peak > 0 else 0

                # 写入每日净值
                cur.execute(
                    "INSERT INTO sim_daily_nav "
                    "(account_id, trade_date, total_value, cash, market_value, "
                    "daily_return, cumulative_return, max_drawdown) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE "
                    "total_value=VALUES(total_value), cash=VALUES(cash), "
                    "market_value=VALUES(market_value), daily_return=VALUES(daily_return), "
                    "cumulative_return=VALUES(cumulative_return), max_drawdown=VALUES(max_drawdown)",
                    (self.account_id, trade_date,
                     round(total_value, 2), round(acct["cash"], 2),
                     round(market_value, 2),
                     round(daily_return, 4), round(cumulative_return, 4),
                     round(max_drawdown, 4)),
                )
        finally:
            conn.close()

        return {
            "trade_date": str(trade_date),
            "total_value": round(total_value, 2),
            "cash": round(acct["cash"], 2),
            "market_value": round(market_value, 2),
            "daily_return": round(daily_return, 4),
            "cumulative_return": round(cumulative_return, 4),
            "max_drawdown": round(max_drawdown, 4),
        }
