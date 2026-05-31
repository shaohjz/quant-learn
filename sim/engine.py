"""
sim/engine.py
模拟交易引擎 — 管理模拟账户、持仓、交易记录（SQLite 版）

注意：此引擎只负责"账本"逻辑（资金/持仓/交易/净值），下单的具体执行
（模拟撮合 vs 实盘 QMT）由 broker 层负责。SimEngine 也会被 SimBroker 使用。
"""

from datetime import date as Date
from sim.db import get_conn
from sim.config import risk_params


# 费用常量（A 股个人投资者参数）
COMMISSION_RATE = 0.0003   # 佣金万3
MIN_COMMISSION = 5.0       # 最低佣金 5 元
STAMP_TAX_RATE = 0.001     # 印花税千1（仅卖出）


def _row_to_dict(row):
    return dict(row) if row is not None else None


class SimEngine:
    """模拟交易引擎（账本 + 撮合）"""

    def __init__(self, account_id: int = 1):
        self.account_id = account_id

    def _count_new_positions_today(self, trade_date: str) -> int:
        """统计今天新建的仓位数（首次买入某股票，非加仓）"""
        conn = get_conn()
        try:
            cur = conn.cursor()
            # 找出今天账户内所有首次出现的持仓（即今天之前无持仓，今天有买入）
            # 方法：统计今天有 BUY 交易、且在今天之前没有该 stock_code 持仓记录的股票数
            cur.execute("""
                SELECT COUNT(DISTINCT stock_code)
                FROM sim_trades t
                WHERE t.account_id = ?
                  AND t.direction = 'BUY'
                  AND t.trade_date = ?
                  AND stock_code NOT IN (
                      SELECT DISTINCT stock_code
                      FROM sim_trades
                      WHERE account_id = ?
                        AND direction = 'BUY'
                        AND trade_date < ?
                  )
            """, (self.account_id, trade_date, self.account_id, trade_date))
            row = cur.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    # ---------- 账户 ----------
    def get_account(self) -> dict:
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, account_name, initial_cash, cash, total_value, updated_at "
                "FROM sim_account WHERE id = ?",
                (self.account_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"账户 {self.account_id} 不存在")
            return {
                "id": row["id"],
                "account_name": row["account_name"],
                "initial_cash": float(row["initial_cash"]),
                "cash": float(row["cash"]),
                "total_value": float(row["total_value"]),
                "updated_at": row["updated_at"],
            }
        finally:
            conn.close()

    # ---------- 持仓 ----------
    def get_positions(self) -> list:
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, stock_code, stock_name, quantity, avg_cost, "
                "current_price, market_value, pnl, pnl_pct "
                "FROM sim_positions WHERE account_id = ? AND quantity > 0",
                (self.account_id,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def _get_position(self, stock_code: str):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, quantity, avg_cost FROM sim_positions "
                "WHERE account_id = ? AND stock_code = ? AND quantity > 0",
                (self.account_id, stock_code),
            )
            row = cur.fetchone()
            if row:
                return {"id": row["id"], "quantity": row["quantity"], "avg_cost": float(row["avg_cost"])}
            return None
        finally:
            conn.close()

    # ---------- 买入 ----------
    def buy(self, stock_code: str, price: float, quantity: int,
            stock_name: str = "", signal_reason: str = "",
            trade_date: Date = None,
            broker: str = "sim", broker_order_id: str = None,
            signal_detail: dict = None) -> dict:
        """
        买入（佣金万3，最低5元）
        返回 {success, msg, amount, commission}

        broker / broker_order_id：当上层是实盘 broker 时填充，便于对账。
        """
        if quantity <= 0 or price <= 0:
            return {"success": False, "msg": "价格/数量无效"}

        # ---- REQ-038 硬上限检查 ----
        risk = risk_params()

        # 1) 总持仓数上限（含本次新建）
        positions = self.get_positions()
        existing_codes = {p["stock_code"] for p in positions}
        if stock_code not in existing_codes:
            # 本次是新建仓（非加仓），总持仓数会 +1
            if len(existing_codes) >= risk.get("max_total_positions", 6):
                return {
                    "success": False,
                    "msg": f"持仓数量达到硬上限 {risk.get('max_total_positions', 6)}，无法新建 {stock_code}",
                }

        # 2) 单日新建仓位数上限
        trade_date = trade_date or Date.today()
        new_positions_today = self._count_new_positions_today(str(trade_date))
        if stock_code not in existing_codes:
            # 只有新建仓（非加仓）才计入单日新建上限
            if new_positions_today >= risk.get("max_daily_new_positions", 3):
                return {
                    "success": False,
                    "msg": f"今日新建仓位已达上限 {risk.get('max_daily_new_positions', 3)}，无法新建 {stock_code}",
                }

        # 重置 trade_date（上面可能已赋值）
        trade_date = trade_date or Date.today()

        # 数量向下取整到 100 股
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
            cur = conn.cursor()
            # 1. 扣减现金
            new_cash = acct["cash"] - total_cost
            cur.execute("UPDATE sim_account SET cash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (round(new_cash, 2), self.account_id))

            # 2. 更新/新建持仓
            pos = self._get_position(stock_code)
            if pos:
                old_qty = pos["quantity"]
                old_cost = pos["avg_cost"]
                new_qty = old_qty + quantity
                new_avg = (old_cost * old_qty + price * quantity) / new_qty
                cur.execute(
                    "UPDATE sim_positions SET quantity = ?, avg_cost = ?, "
                    "current_price = ?, market_value = ?, pnl = ?, pnl_pct = ?, "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
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
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (self.account_id, stock_code, stock_name, quantity,
                     round(price, 4), round(price, 4),
                     round(price * quantity, 2), 0, 0),
                )

            # 3. 写交易记录
            import json as _json, sqlite3 as _sq
            _detail_str = _json.dumps(signal_detail, ensure_ascii=False) if signal_detail else None
            # 动态检测 signal_detail 列是否存在（兼容旧表）
            _cols = [r[1] for r in cur.execute('PRAGMA table_info(sim_trades)').fetchall()]
            _has_detail = 'signal_detail' in _cols
            if _has_detail:
                _sql = (
                    "INSERT INTO sim_trades "
                    "(account_id, trade_date, stock_code, stock_name, direction, "
                    "price, quantity, amount, commission, tax, signal_reason, "
                    "broker, broker_order_id, signal_detail) "
                    "VALUES (?, ?, ?, ?, 'BUY', ?, ?, ?, ?, 0, ?, ?, ?, ?)"
                )
                _params = (self.account_id, str(trade_date), stock_code, stock_name,
                          round(price, 4), quantity, round(amount, 2),
                          round(commission, 2), signal_reason,
                          broker, broker_order_id, _detail_str)
            else:
                _sql = (
                    "INSERT INTO sim_trades "
                    "(account_id, trade_date, stock_code, stock_name, direction, "
                    "price, quantity, amount, commission, tax, signal_reason, "
                    "broker, broker_order_id) "
                    "VALUES (?, ?, ?, ?, 'BUY', ?, ?, ?, ?, 0, ?, ?, ?)"
                )
                _params = (self.account_id, str(trade_date), stock_code, stock_name,
                          round(price, 4), quantity, round(amount, 2),
                          round(commission, 2), signal_reason,
                          broker, broker_order_id)
            cur.execute(_sql, _params)
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
             trade_date: Date = None,
             broker: str = "sim", broker_order_id: str = None,
             signal_detail: dict = None) -> dict:
        """卖出（佣金万3最低5元 + 印花税千1）"""
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
            cur = conn.cursor()
            # 1. 增加现金
            acct = self.get_account()
            new_cash = acct["cash"] + net_income
            cur.execute("UPDATE sim_account SET cash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (round(new_cash, 2), self.account_id))

            # 2. 更新持仓
            remain = pos["quantity"] - quantity
            if remain > 0:
                cur.execute(
                    "UPDATE sim_positions SET quantity = ?, current_price = ?, "
                    "market_value = ?, pnl = ?, pnl_pct = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (remain, price, round(price * remain, 2),
                     round((price - pos["avg_cost"]) * remain, 2),
                     round((price - pos["avg_cost"]) / pos["avg_cost"], 4) if pos["avg_cost"] else 0,
                     pos["id"]),
                )
            else:
                cur.execute(
                    "UPDATE sim_positions SET quantity = 0, market_value = 0, "
                    "pnl = 0, pnl_pct = 0, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (pos["id"],),
                )

            # 3. 写交易记录
            import json as _json
            _detail_str = _json.dumps(signal_detail, ensure_ascii=False) if signal_detail else None
            cur.execute(
                "INSERT INTO sim_trades "
                "(account_id, trade_date, stock_code, stock_name, direction, "
                "price, quantity, amount, commission, tax, signal_reason, "
                "broker, broker_order_id, signal_detail) "
                "VALUES (?, ?, ?, ?, 'SELL', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self.account_id, str(trade_date), stock_code, stock_name,
                 round(price, 4), quantity, round(amount, 2),
                 round(commission, 2), round(tax, 2), signal_reason,
                 broker, broker_order_id, _detail_str),
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
        """price_dict: {stock_code: latest_price}"""
        conn = get_conn()
        try:
            cur = conn.cursor()
            for code, p in price_dict.items():
                cur.execute(
                    "UPDATE sim_positions SET "
                    "current_price = ?, "
                    "market_value = quantity * ?, "
                    "pnl = (quantity * ?) - (quantity * avg_cost), "
                    "pnl_pct = CASE WHEN avg_cost > 0 THEN (? - avg_cost) / avg_cost ELSE 0 END, "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE account_id = ? AND stock_code = ? AND quantity > 0",
                    (p, p, p, p, self.account_id, code),
                )
        finally:
            conn.close()

    # ---------- 每日结算 ----------
    def daily_settle(self, trade_date: Date = None) -> dict:
        """每日结算：刷新总资产、记录净值。SQLite UPSERT 写法。"""
        trade_date = trade_date or Date.today()
        acct = self.get_account()
        positions = self.get_positions()

        market_value = sum(float(p["market_value"] or 0) for p in positions)
        total_value = acct["cash"] + market_value

        conn = get_conn()
        try:
            cur = conn.cursor()
            # 更新账户总资产
            cur.execute(
                "UPDATE sim_account SET total_value = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (round(total_value, 2), self.account_id),
            )

            initial_cash = acct["initial_cash"]
            cumulative_return = (total_value - initial_cash) / initial_cash if initial_cash else 0

            # 前一日净值
            cur.execute(
                "SELECT total_value FROM sim_daily_nav "
                "WHERE account_id = ? AND trade_date < ? "
                "ORDER BY trade_date DESC LIMIT 1",
                (self.account_id, str(trade_date)),
            )
            prev = cur.fetchone()
            prev_value = float(prev["total_value"]) if prev else initial_cash
            daily_return = (total_value - prev_value) / prev_value if prev_value else 0

            # 历史峰值（包含当前）
            cur.execute(
                "SELECT MAX(total_value) AS peak FROM sim_daily_nav WHERE account_id = ?",
                (self.account_id,),
            )
            peak_row = cur.fetchone()
            peak = float(peak_row["peak"]) if peak_row and peak_row["peak"] else initial_cash
            peak = max(peak, total_value)
            max_drawdown = (peak - total_value) / peak if peak > 0 else 0

            # SQLite UPSERT
            cur.execute(
                "INSERT INTO sim_daily_nav "
                "(account_id, trade_date, total_value, cash, market_value, "
                "daily_return, cumulative_return, max_drawdown) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(account_id, trade_date) DO UPDATE SET "
                "total_value = excluded.total_value, cash = excluded.cash, "
                "market_value = excluded.market_value, daily_return = excluded.daily_return, "
                "cumulative_return = excluded.cumulative_return, "
                "max_drawdown = excluded.max_drawdown",
                (self.account_id, str(trade_date),
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
