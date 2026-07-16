"""
sim/engine.py
模拟交易引擎 — 管理模拟账户、持仓、交易记录（SQLite 版）

注意：此引擎只负责"账本"逻辑（资金/持仓/交易/净值），下单的具体执行
（模拟撮合 vs 实盘 QMT）由 broker 层负责。SimEngine 也会被 SimBroker 使用。
"""

from datetime import date as Date
from sim.db import (
    get_conn,
    ensure_sim_trades_detail_columns,
    ensure_sim_positions_trailing_columns,
    calc_trailing_stop_price,
)
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
        # [REQ-001] 启动时校验账户映射一致性（config vs DB）
        self._validate_account_consistency()

    def _validate_account_consistency(self):
        """[REQ-001][REQ-094] 校验 config.yaml 与 sim_account DB 的一致性。

        检查项：
        1. config initial_cash vs DB initial_cash（本金变更检测）
        2. 记录变更事件到 sim_account_events
        3. 同步方向：DB 为权威来源（含历史交易累计影响），
           若不一致则警告用户更新 config，**不**覆盖 DB 数据

        REQ-094 修复：原逻辑错误地以 config 为准覆盖 DB，
        导致 sim_account_events 表中产生了6条错误同步记录。
        现改为 DB 为权威来源，同步方向为 DB→config（仅警告，不自动修改 config）。
        """
        try:
            from sim.config import get_account_config
            acct_cfg = get_account_config(self.account_id)
            cfg_initial_cash = float(acct_cfg.get("initial_cash", 100000.0))
        except Exception:
            return  # config 读取失败，跳过校验

        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT initial_cash, cash, total_value FROM sim_account WHERE id = ?",
                (self.account_id,),
            )
            row = cur.fetchone()
            if not row:
                return

            db_initial_cash = float(row["initial_cash"])
            db_cash = float(row["cash"])
            db_total = float(row["total_value"])

            if abs(db_initial_cash - cfg_initial_cash) > 0.01:
                # [REQ-094] DB 与 config 不一致时，DB 为权威来源
                # DB 中的 initial_cash 反映了历史交易的全部累计影响，
                # 用 config 覆盖 DB 会破坏累计收益率计算和净值序列一致性。
                # 正确做法：保留 DB 值，警告用户需要更新 config。
                try:
                    from sim.db import record_account_event
                    reason = (
                        f"[REQ-094] 本金不一致（DB权威）: "
                        f"DB.initial_cash={db_initial_cash:,.0f}, "
                        f"config.initial_cash={cfg_initial_cash:,.0f}. "
                        f"DB 为权威来源（含历史交易累计影响），"
                        f"请更新 config.yaml 中 accounts.learn.initial_cash 为 {db_initial_cash:,.0f} 以消除此警告。"
                        f"本次不同步 DB，保持 DB 值不变。"
                    )
                    record_account_event(
                        account_id=self.account_id,
                        event_type="config_sync",
                        event_date=Date.today(),
                        old_initial_cash=cfg_initial_cash,
                        new_initial_cash=db_initial_cash,
                        old_total_value=db_total,
                        new_total_value=db_total,
                        reason=reason,
                        source="engine.init",
                    )
                except Exception:
                    pass

                # [REQ-094] 不修改 DB，只输出警告
                # 旧行为（已修复）：cur.execute UPDATE sim_account SET initial_cash = cfg 值
                # 这会导致累计收益率计算基准被错误篡改
                print(
                    f"[REQ-001/REQ-094] ⚠️ 账户 {self.account_id} 本金不一致: "
                    f"DB={db_initial_cash:,.0f} (权威) vs config={cfg_initial_cash:,.0f}。"
                    f"DB 为权威来源（含历史交易累计影响），不会覆盖 DB 数据。"
                    f"请更新 config.yaml 以消除此警告。"
                )
        finally:
            conn.close()

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
    def get_account(self, use_config_initial_cash: bool = False) -> dict:
        """获取账户信息。

        Args:
            use_config_initial_cash: [REQ-094] 默认 False，以 DB 中的 initial_cash 为准。
                DB 为权威来源（含历史交易累计影响），不再用 config 覆盖。
                设为 True 仅在需要与旧 config 基准对齐时使用（过渡兼容）。
        """
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
            result = {
                "id": row["id"],
                "account_name": row["account_name"],
                "initial_cash": float(row["initial_cash"]),
                "cash": float(row["cash"]),
                "total_value": float(row["total_value"]),
                "updated_at": row["updated_at"],
            }
            # [REQ-001] 若启用，用 config 值覆盖（确保收益率基准正确）
            if use_config_initial_cash:
                try:
                    from sim.config import get_account_config
                    acct_cfg = get_account_config(self.account_id)
                    result["initial_cash"] = float(acct_cfg.get("initial_cash", result["initial_cash"]))
                except Exception:
                    pass
            return result
        finally:
            conn.close()

    # ---------- 持仓 ----------
    def get_positions(self) -> list:
        conn = get_conn()
        try:
            cur = conn.cursor()
            ensure_sim_positions_trailing_columns(cur)
            cur.execute(
                "SELECT id, stock_code, stock_name, quantity, avg_cost, "
                "current_price, market_value, pnl, pnl_pct, "
                "trailing_stop_price, highest_price "
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

    def _has_buy_today(self, stock_code: str, trade_date: str) -> bool:
        """REQ-051: 检查今日是否已买入同一股票（用于多信号去重）"""
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM sim_trades "
                "WHERE account_id = ? AND stock_code = ? AND trade_date = ? "
                "AND direction = 'BUY' LIMIT 1",
                (self.account_id, stock_code, trade_date),
            )
            return cur.fetchone() is not None
        finally:
            conn.close()

    def _has_sell_today(self, stock_code: str, trade_date: str) -> bool:
        """BUG-011: 检查今日是否已卖出同一股票（同日反向交易防御）。

        若今日已有 SELL 成交，则当日不允许再 BUY 同一股票，
        防止 buy_strong + trend_break 同日矛盾信号导致自成交。
        """
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM sim_trades "
                "WHERE account_id = ? AND stock_code = ? AND trade_date = ? "
                "AND direction = 'SELL' LIMIT 1",
                (self.account_id, stock_code, trade_date),
            )
            return cur.fetchone() is not None
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

        # ---- REQ-051: 同一股票同日多信号去重 ----
        # 若今日已有该股票的 BUY 成交，拒绝重复买入（避免同日多信号重复执行）
        trade_date = trade_date or Date.today()
        if self._has_buy_today(stock_code, str(trade_date)):
            return {
                "success": False,
                "msg": f"REQ-051: {stock_code} 今日已有买入成交，拒绝重复买入",
            }

        # ---- BUG-011: 同日反向交易防御 ----
        # 若今日已有该股票的 SELL 成交，拒绝今日再买入
        # 防止 buy_strong + trend_break 同日矛盾信号导致自成交
        if self._has_sell_today(stock_code, str(trade_date)):
            return {
                "success": False,
                "msg": f"BUG-011: {stock_code} 今日已有卖出成交，基于同日反向交易规则拒绝今日再买入",
            }

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

        # ---- REQ-045: 现金过低预警 + 仓位管理 ----
        acct = self.get_account()
        try:
            from sim.cash_warning import check_cash_ratio, suggest_position_size
            _cw = check_cash_ratio(acct["cash"], acct["total_value"])
            if _cw.level == "critical" and stock_code not in existing_codes:
                return {
                    "success": False,
                    "msg": f"REQ-045: {_cw.message}",
                }
            if _cw.level == "low":
                original_qty = quantity
                quantity = suggest_position_size(quantity, _cw)
                if quantity < original_qty:
                    import logging as _logging
                    _logging.getLogger(__name__).warning(
                        "REQ-045: 现金占比 %.1f%% 偏低，买入量 %d→%d",
                        _cw.cash_pct * 100, original_qty, quantity,
                    )
                if quantity == 0:
                    return {
                        "success": False,
                        "msg": f"REQ-045: 现金占比 {_cw.cash_pct:.1%} 过低，建议买入量缩减为0",
                    }
        except Exception as _e:
            import logging as _logging
            _logging.getLogger(__name__).debug("REQ-045 check failed: %s", _e)

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
            ensure_sim_positions_trailing_columns(cur)
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
                    "highest_price = MAX(COALESCE(highest_price, ?), ?), "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (new_qty, round(new_avg, 4), price,
                     round(price * new_qty, 2),
                     round((price - new_avg) * new_qty, 2),
                     round((price - new_avg) / new_avg, 4) if new_avg else 0,
                     price, price,
                     pos["id"]),
                )
            else:
                # REQ-067: 使用统一默认初始止损（-5%），与 calc_trailing_stop_price 保持一致
                from sim.db import get_default_trailing_stop
                init_stop = get_default_trailing_stop(price)
                cur.execute(
                    "INSERT INTO sim_positions "
                    "(account_id, stock_code, stock_name, quantity, avg_cost, "
                    "current_price, market_value, pnl, pnl_pct, "
                    "highest_price, trailing_stop_price) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (self.account_id, stock_code, stock_name, quantity,
                     round(price, 4), round(price, 4),
                     round(price * quantity, 2), 0, 0,
                     round(price, 4), init_stop),
                )

            # 3. 写交易记录：先幂等补齐旧库字段，确保 REQ-032 完整信号解释不会丢失
            import json as _json
            ensure_sim_trades_detail_columns(cur)
            _detail_str = _json.dumps(signal_detail, ensure_ascii=False) if signal_detail else None
            # 动态检测 signal_detail 列是否存在（兼容旧表/异常迁移场景）
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

        # REQ-058: SELL 必须可溯源 —— 禁止写入空 signal_reason，
        # 缺失时用标准格式回填占位（规则名+触发价），避免成交记录 NULL 无法对账。
        if not (signal_reason or "").strip():
            try:
                from sim.sell_signal_audit import build_sell_signal_reason
                signal_reason = build_sell_signal_reason("manual_sell", trigger_price=price)
            except Exception:
                signal_reason = f"manual_sell|触发价{price:.3f}"

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

            # 3. 写交易记录：先幂等补齐旧库字段，确保 REQ-032 完整信号解释不会丢失
            import json as _json
            ensure_sim_trades_detail_columns(cur)
            _detail_str = _json.dumps(signal_detail, ensure_ascii=False) if signal_detail else None
            _cols = [r[1] for r in cur.execute('PRAGMA table_info(sim_trades)').fetchall()]
            _has_detail = 'signal_detail' in _cols
            if _has_detail:
                _sql = (
                    "INSERT INTO sim_trades "
                    "(account_id, trade_date, stock_code, stock_name, direction, "
                    "price, quantity, amount, commission, tax, signal_reason, "
                    "broker, broker_order_id, signal_detail) "
                    "VALUES (?, ?, ?, ?, 'SELL', ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                )
                _params = (self.account_id, str(trade_date), stock_code, stock_name,
                           round(price, 4), quantity, round(amount, 2),
                           round(commission, 2), round(tax, 2), signal_reason,
                           broker, broker_order_id, _detail_str)
            else:
                _sql = (
                    "INSERT INTO sim_trades "
                    "(account_id, trade_date, stock_code, stock_name, direction, "
                    "price, quantity, amount, commission, tax, signal_reason, "
                    "broker, broker_order_id) "
                    "VALUES (?, ?, ?, ?, 'SELL', ?, ?, ?, ?, ?, ?, ?, ?)"
                )
                _params = (self.account_id, str(trade_date), stock_code, stock_name,
                           round(price, 4), quantity, round(amount, 2),
                           round(commission, 2), round(tax, 2), signal_reason,
                           broker, broker_order_id)
            cur.execute(_sql, _params)
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
        """price_dict: {stock_code: latest_price}

        价格刷新时同步抬高 P2 跟踪止损：
        - 浮盈 > 5%  ：止损位 → entry*1.0（保本）
        - 浮盈 > 10% ：止损位 → entry*1.02（保 2% 利润）
        - 浮盈 > 20% ：止损位 → max(entry*1.10, high*0.92)
        止损位和持仓最高价只能上移，不能下移。
        """
        conn = get_conn()
        try:
            cur = conn.cursor()
            ensure_sim_positions_trailing_columns(cur)
            for code, p in price_dict.items():
                cur.execute(
                    "SELECT id, avg_cost, highest_price, trailing_stop_price "
                    "FROM sim_positions WHERE account_id = ? AND stock_code = ? AND quantity > 0",
                    (self.account_id, code),
                )
                row = cur.fetchone()
                if not row:
                    continue
                latest = float(p)
                entry = float(row["avg_cost"] or 0)
                highest = max(float(row["highest_price"] or entry or 0), latest)
                trailing, _reason = calc_trailing_stop_price(entry, highest, row["trailing_stop_price"])
                cur.execute(
                    "UPDATE sim_positions SET "
                    "current_price = ?, "
                    "market_value = quantity * ?, "
                    "pnl = (quantity * ?) - (quantity * avg_cost), "
                    "pnl_pct = CASE WHEN avg_cost > 0 THEN (? - avg_cost) / avg_cost ELSE 0 END, "
                    "highest_price = ?, trailing_stop_price = ?, "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (latest, latest, latest, latest,
                     round(highest, 4), trailing if trailing > 0 else None,
                     row["id"]),
                )
        finally:
            conn.close()

    # ---------- 每日结算 ----------
    def daily_settle(self, trade_date: Date = None, backfill_missing: bool = True) -> dict:
        """每日结算：刷新总资产、记录净值。SQLite UPSERT 写法。

        新增 REQ-001 资金口径跳变检测：
        - 检测总资产/现金相对上一净值日是否跳变超过 50%
        - 跳变时记录事件到 sim_account_events
        - 跳变时 daily_return 设为 None，cumulative_return 重新基于 initial_cash 计算

        REQ-095: 新增 backfill_missing 参数。当上次 NAV 日与当前日期间隔 >1 天时，
        自动补写缺失日期的 NAV（继承上一天的值，daily_return=0）。
        """
        trade_date = trade_date or Date.today()
        # [REQ-094] 使用 DB 的 initial_cash 作为基准（DB 为权威来源，含历史交易累计影响）
        acct = self.get_account(use_config_initial_cash=False)
        db_initial_cash = acct["initial_cash"]
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

            initial_cash = db_initial_cash  # [REQ-094] 始终以 DB initial_cash 为基准
            cumulative_return = (total_value - initial_cash) / initial_cash if initial_cash else 0

            # 前一日净值
            cur.execute(
                "SELECT total_value, cash, trade_date, cash_jump_detected "
                "FROM sim_daily_nav "
                "WHERE account_id = ? AND trade_date < ? "
                "ORDER BY trade_date DESC LIMIT 1",
                (self.account_id, str(trade_date)),
            )
            prev = cur.fetchone()
            prev_value = float(prev["total_value"]) if prev else db_initial_cash

            # ---- REQ-095: 自动补写缺失日期的 NAV ----
            if backfill_missing and prev:
                from datetime import date as _Date, timedelta as _Timedelta
                prev_date = _Date.fromisoformat(str(prev["trade_date"]))
                target_date = _Date.fromisoformat(str(trade_date)) if isinstance(trade_date, str) else trade_date
                gap_days = (target_date - prev_date).days
                if gap_days > 1:
                    # 需要补写 prev_date+1 到 target_date-1 的 NAV
                    for offset in range(1, gap_days):
                        fill_date = prev_date + _Timedelta(days=offset)
                        fill_date_str = fill_date.isoformat()
                        # 检查是否已有（幂等）
                        cur.execute(
                            "SELECT 1 FROM sim_daily_nav WHERE account_id=? AND trade_date=?",
                            (self.account_id, fill_date_str),
                        )
                        if cur.fetchone():
                            continue
                        # 用前一日值填充（非交易日 daily_return=0）
                        cur.execute(
                            "INSERT OR IGNORE INTO sim_daily_nav "
                            "(account_id, trade_date, total_value, cash, market_value, "
                            "daily_return, cumulative_return, max_drawdown, "
                            "cash_jump_detected, cash_jump_reason) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (self.account_id, fill_date_str,
                             prev["total_value"], prev["cash"],
                             (prev["total_value"] or 0) - (prev["cash"] or 0),
                             0.0,
                             round((float(prev["total_value"]) - initial_cash) / initial_cash, 4) if initial_cash else 0,
                             0.0,
                             0,
                             f"REQ-095 auto-backfill: 非交易日自动补写，继承 {prev['trade_date']} NAV"),
                        )
                        print(
                            f"[REQ-095] 自动补写 NAV: {fill_date_str} "
                            f"(继承 {prev['trade_date']}, daily_return=0)"
                        )
                    conn.commit()

            # [REQ-001] 资金口径跳变检测（阈值降低到 20%）
            cash_jump_detected = 0
            cash_jump_reason = None
            if prev:
                prev_total = float(prev["total_value"])
                prev_cash = float(prev["cash"])
                total_jump = (total_value - prev_total) / prev_total if prev_total > 0 else 0
                cash_jump = (acct["cash"] - prev_cash) / prev_cash if prev_cash > 0 else 0
                # 检测跳变 或 config 本金变更
                config_changed = False
                try:
                    from sim.db import fetch_account_events
                    events = fetch_account_events(self.account_id, limit=10)
                    for ev in events:
                        if ev["event_type"] in ("config_sync", "reset") and str(ev["event_date"]) >= str(prev["trade_date"]):
                            config_changed = True
                            break
                except Exception:
                    pass

                if abs(total_jump) >= 0.20 or abs(cash_jump) >= 0.20 or config_changed:
                    cash_jump_detected = 1
                    reasons = []
                    if abs(total_jump) >= 0.20:
                        reasons.append(f"总资产跳变 {total_jump*100:+.2f}%")
                    if abs(cash_jump) >= 0.20:
                        reasons.append(f"现金跳变 {cash_jump*100:+.2f}%")
                    if config_changed:
                        reasons.append("config initial_cash 变更")
                    cash_jump_reason = "; ".join(reasons) + (
                        f" (¥{prev_total:,.2f}→¥{total_value:,.2f})"
                    )
                    # 记录账户事件
                    try:
                        from sim.db import record_account_event
                        record_account_event(
                            account_id=self.account_id,
                            event_type="jump_detected",
                            event_date=trade_date,
                            old_initial_cash=None,
                            new_initial_cash=None,
                            old_total_value=prev_total,
                            new_total_value=total_value,
                            reason=cash_jump_reason,
                            source="engine.daily_settle",
                        )
                    except Exception:
                        pass

            # 计算日收益率（REQ-061 修复：始终计算并存储，不再设为 None）
            daily_return = (total_value - prev_value) / prev_value if prev_value else 0
            # 跳变时在 cash_jump_reason 中记录原因（已在上面赋值），daily_return 仍然存储

            # 历史峰值（包含当前）
            cur.execute(
                "SELECT MAX(total_value) AS peak FROM sim_daily_nav WHERE account_id = ?",
                (self.account_id,),
            )
            peak_row = cur.fetchone()
            peak = float(peak_row["peak"]) if peak_row and peak_row["peak"] else db_initial_cash
            peak = max(peak, total_value)
            max_drawdown = (peak - total_value) / peak if peak > 0 else 0

            # SQLite UPSERT (含跳变标记)
            cur.execute(
                "INSERT INTO sim_daily_nav "
                "(account_id, trade_date, total_value, cash, market_value, "
                "daily_return, cumulative_return, max_drawdown, "
                "cash_jump_detected, cash_jump_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(account_id, trade_date) DO UPDATE SET "
                "total_value = excluded.total_value, cash = excluded.cash, "
                "market_value = excluded.market_value, daily_return = excluded.daily_return, "
                "cumulative_return = excluded.cumulative_return, "
                "max_drawdown = excluded.max_drawdown, "
                "cash_jump_detected = excluded.cash_jump_detected, "
                "cash_jump_reason = excluded.cash_jump_reason",
                (self.account_id, str(trade_date),
                 round(total_value, 2), round(acct["cash"], 2),
                 round(market_value, 2),
                 daily_return,  # 跳变时 None
                 round(cumulative_return, 4),
                 round(max_drawdown, 4),
                 cash_jump_detected,
                 cash_jump_reason),
            )
        finally:
            conn.close()

        return {
            "trade_date": str(trade_date),
            "total_value": round(total_value, 2),
            "cash": round(acct["cash"], 2),
            "market_value": round(market_value, 2),
            "daily_return": daily_return,  # 跳变时 None
            "cumulative_return": round(cumulative_return, 4),
            "max_drawdown": round(max_drawdown, 4),
            "cash_jump_detected": bool(cash_jump_detected),
            "cash_jump_reason": cash_jump_reason,
        }
