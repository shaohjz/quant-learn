"""
sim/db.py
SQLite 持久层 - 跨平台、零配置、单文件。

数据库路径默认在项目根目录的 data/sim.db,可通过环境变量 QUANT_DB_PATH 覆盖。
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


# 默认数据库路径:项目根目录/data/sim.db
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _PROJECT_ROOT / "data" / "sim.db"
DB_PATH = Path(os.environ.get("QUANT_DB_PATH", str(_DEFAULT_DB)))

# 默认初始资金(可通过环境变量覆盖)
DEFAULT_INITIAL_CASH = float(os.environ.get("QUANT_INITIAL_CASH", "10000"))


def _ensure_db_dir():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    """获取一个 SQLite 连接(启用外键,使用 Row 工厂方便按列名取值)。"""
    _ensure_db_dir()
    conn = sqlite3.connect(str(DB_PATH), timeout=30, isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # 写并发更友好
    return conn


@contextmanager
def cursor():
    """上下文管理器写法,少写几行 close。"""
    conn = get_conn()
    try:
        yield conn.cursor()
    finally:
        conn.close()


def init_tables():
    """创建模拟交易相关的表并初始化默认账户。SQLite 兼容写法。"""
    conn = get_conn()
    try:
        cur = conn.cursor()

        # 模拟账户
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sim_account (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_name TEXT DEFAULT 'default',
                initial_cash REAL DEFAULT 10000.00,
                cash REAL DEFAULT 10000.00,
                total_value REAL DEFAULT 10000.00,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 模拟持仓
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sim_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER DEFAULT 1,
                stock_code TEXT,
                stock_name TEXT,
                quantity INTEGER DEFAULT 0,
                avg_cost REAL,
                current_price REAL,
                market_value REAL,
                pnl REAL,
                pnl_pct REAL,
                trailing_stop_price REAL DEFAULT NULL,
                highest_price REAL DEFAULT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 交易记录
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sim_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER DEFAULT 1,
                trade_date DATE,
                stock_code TEXT,
                stock_name TEXT,
                direction TEXT,        -- BUY / SELL
                price REAL,
                quantity INTEGER,
                amount REAL,
                commission REAL,
                tax REAL,
                signal_reason TEXT,
                broker TEXT DEFAULT 'sim',  -- sim / qmt / ...
                broker_order_id TEXT,       -- 实盘委托号
                signal_detail TEXT,         -- REQ-032 完整信号解释（JSON）
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 每日净值
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sim_daily_nav (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER DEFAULT 1,
                trade_date DATE,
                total_value REAL,
                cash REAL,
                market_value REAL,
                daily_return REAL,
                cumulative_return REAL,
                max_drawdown REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (account_id, trade_date)
            )
        """)

        # 账户事件表(REQ-001: 资金口径变更追踪)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sim_account_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER DEFAULT 1,
                event_type TEXT NOT NULL,       -- reset / topup / withdrawal / config_sync / manual
                event_date DATE,
                old_initial_cash REAL,
                new_initial_cash REAL,
                old_total_value REAL,
                new_total_value REAL,
                reason TEXT,                    -- 变更原因说明
                source TEXT DEFAULT 'system',   -- config / db / manual / engine
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 兼容旧库：CREATE TABLE IF NOT EXISTS 不会给既有表补列。
        _ensure_sim_trades_detail_columns(cur)
        _ensure_sim_positions_trailing_columns(cur)
        _ensure_sim_daily_nav_jump_columns(cur)
        _ensure_sim_account_events_index(cur)

        # 索引
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_date ON sim_trades(trade_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_code ON sim_trades(stock_code)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pos_code ON sim_positions(stock_code)")

        # 订单记录(OmsEngine EVENT_ORDER 持久化)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sim_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER DEFAULT 1,
                order_id TEXT,              -- vnpy 内部 order_id / broker_order_id
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                direction TEXT NOT NULL,    -- BUY / SELL
                offset TEXT,               -- OPEN / CLOSE
                price REAL,
                quantity INTEGER,
                traded INTEGER DEFAULT 0,   -- 已成交数量
                status TEXT,               -- SUBMITTED / PART_TRADED / ALL_TRADED / CANCELLED / REJECTED
                order_time TIMESTAMP,       -- 下单时间
                cancel_time TIMESTAMP,     -- 撤单时间
                broker TEXT DEFAULT 'sim',
                broker_order_id TEXT,       -- 券商委托号
                strategy_name TEXT,         -- 触发策略名
                signal_reason TEXT,        -- 信号原因
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 成交记录(OmsEngine EVENT_TRADE 持久化,比 sim_trades 更细粒度)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sim_fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER DEFAULT 1,
                order_id TEXT,              -- 关联 sim_orders.order_id
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                direction TEXT NOT NULL,    -- BUY / SELL
                trade_price REAL NOT NULL, -- 成交价格
                trade_volume INTEGER,       -- 成交数量
                trade_amount REAL,          -- 成交金额
                commission REAL DEFAULT 0,  -- 佣金
                tax REAL DEFAULT 0,         -- 印花税
                trade_time TIMESTAMP,       -- 成交时间
                broker TEXT DEFAULT 'sim',
                broker_trade_id TEXT,       -- 券商成交编号
                strategy_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # sim_orders 索引
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_date ON sim_orders(order_time)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_code ON sim_orders(stock_code)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON sim_orders(status)")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_broker_id ON sim_orders(broker_order_id) WHERE broker_order_id IS NOT NULL AND broker_order_id != ''")

        # sim_fills 索引
        cur.execute("CREATE INDEX IF NOT EXISTS idx_fills_date ON sim_fills(trade_time)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_fills_code ON sim_fills(stock_code)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_fills_order ON sim_fills(order_id)")

        # 初始化默认账户(如果不存在)
        cur.execute("SELECT id FROM sim_account WHERE id = 1")
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO sim_account (id, account_name, initial_cash, cash, total_value) "
                "VALUES (1, 'default', ?, ?, ?)",
                (DEFAULT_INITIAL_CASH, DEFAULT_INITIAL_CASH, DEFAULT_INITIAL_CASH),
            )
            print(f"  ✓ 默认账户已创建(初始资金 {DEFAULT_INITIAL_CASH:,.2f})")
        else:
            print("  ✓ 默认账户已存在")

        print(f"  ✓ 所有表已创建/确认 (DB={DB_PATH})")
    finally:
        conn.close()


def _ensure_sim_positions_trailing_columns(cur) -> None:
    """确保 sim_positions 具备 REQ-041 跟踪止损字段。

    CREATE TABLE IF NOT EXISTS 不会给旧库补列；本迁移同时补齐
    trailing_stop_price（当前生效跟踪止损）和 highest_price（持仓后最高价）。
    highest_price 默认可为空，首次价格更新/买入时再以成本或现价初始化。
    """
    cols = {r[1] for r in cur.execute("PRAGMA table_info(sim_positions)").fetchall()}
    if "trailing_stop_price" not in cols:
        cur.execute("ALTER TABLE sim_positions ADD COLUMN trailing_stop_price REAL DEFAULT NULL")
    if "highest_price" not in cols:
        cur.execute("ALTER TABLE sim_positions ADD COLUMN highest_price REAL DEFAULT NULL")


def ensure_sim_positions_trailing_columns(cur=None) -> None:
    """公开迁移入口：幂等补齐 REQ-041 跟踪止损字段。"""
    if cur is not None:
        _ensure_sim_positions_trailing_columns(cur)
        return
    conn = get_conn()
    try:
        _ensure_sim_positions_trailing_columns(conn.cursor())
    finally:
        conn.close()


def calc_trailing_stop_price(entry_price: float, highest_price: float, current_trailing: float | None = None) -> tuple[float, str]:
    """按 REQ-041 计算跟踪止损价；结果只能上移不能下移。"""
    current = float(current_trailing or 0.0)
    if entry_price <= 0 or highest_price <= 0:
        return current, ""

    profit_pct = (highest_price - entry_price) / entry_price
    if profit_pct > 0.20:
        candidate = max(entry_price * 1.10, highest_price * 0.92)
        reason = "浮盈>20%，跟踪止损=max(entry*1.10, high*0.92)"
    elif profit_pct > 0.10:
        candidate = entry_price * 1.02
        reason = "浮盈>10%，止损抬到 entry*1.02"
    elif profit_pct > 0.05:
        candidate = entry_price * 1.00
        reason = "浮盈>5%，止损抬到保本位"
    else:
        candidate = current
        reason = "浮盈未超过5%，跟踪止损未启动"

    candidate = round(float(candidate or 0.0), 4)
    if current > candidate:
        return current, "保持原跟踪止损，不下移"
    return candidate, reason


def _ensure_sim_trades_detail_columns(cur) -> None:
    """确保 sim_trades 具备完整信号解释字段（REQ-032）。

    旧的 sim_live_mirror.db 可能只有 signal_reason 短文本；在写入成交前补齐
    signal_detail，避免完整触发规则、指标快照、阈值、策略版本等上下文被静默丢弃。
    """
    cols = {r[1] for r in cur.execute("PRAGMA table_info(sim_trades)").fetchall()}
    if "signal_detail" not in cols:
        cur.execute("ALTER TABLE sim_trades ADD COLUMN signal_detail TEXT")
    # 历史脚本中已使用这两个字段；一并幂等补齐，降低旧库插入失败概率。
    if "trade_time" not in cols:
        cur.execute("ALTER TABLE sim_trades ADD COLUMN trade_time TEXT")
    if "trade_context" not in cols:
        cur.execute("ALTER TABLE sim_trades ADD COLUMN trade_context TEXT")


def _ensure_sim_daily_nav_jump_columns(cur) -> None:
    """确保 sim_daily_nav 具备资金跳变标记字段(REQ-001)。"""
    cols = {r[1] for r in cur.execute("PRAGMA table_info(sim_daily_nav)").fetchall()}
    if "cash_jump_detected" not in cols:
        cur.execute("ALTER TABLE sim_daily_nav ADD COLUMN cash_jump_detected INTEGER DEFAULT 0")
    if "cash_jump_reason" not in cols:
        cur.execute("ALTER TABLE sim_daily_nav ADD COLUMN cash_jump_reason TEXT")


def _ensure_sim_account_events_index(cur) -> None:
    """确保 sim_account_events 有索引。"""
    cur.execute("CREATE INDEX IF NOT EXISTS idx_acct_events_account ON sim_account_events(account_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_acct_events_date ON sim_account_events(event_date)")


def ensure_sim_trades_detail_columns(cur=None) -> None:
    """公开迁移入口：在成交写入前幂等补齐 REQ-032 所需字段。

    可传入当前事务的 cursor，避免在已有写事务中另开连接导致 SQLite 锁冲突。
    """
    if cur is not None:
        _ensure_sim_trades_detail_columns(cur)
        return
    conn = get_conn()
    try:
        _ensure_sim_trades_detail_columns(conn.cursor())
    finally:
        conn.close()


# ============================================================
# sim_orders / sim_fills 持久化接口(OmsEngine 回放支撑)
# ============================================================

def insert_order(
    account_id: int = 1,
    order_id: str = "",
    stock_code: str = "",
    stock_name: str = "",
    direction: str = "",
    offset: str = "",
    price: float = 0.0,
    quantity: int = 0,
    traded: int = 0,
    status: str = "SUBMITTED",
    order_time=None,
    cancel_time=None,
    broker: str = "sim",
    broker_order_id: str = "",
    strategy_name: str = "",
    signal_reason: str = "",
) -> int:
    """写入一笔订单,返回 row id。"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sim_orders
            (account_id, order_id, stock_code, stock_name, direction, offset,
             price, quantity, traded, status, order_time, cancel_time,
             broker, broker_order_id, strategy_name, signal_reason)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            account_id, order_id, stock_code, stock_name, direction, offset,
            price, quantity, traded, status, order_time, cancel_time,
            broker, broker_order_id, strategy_name, signal_reason,
        ))
        return cur.lastrowid
    finally:
        conn.close()


def update_order_by_broker_id(
    broker_order_id: str,
    traded: int | None = None,
    status: str | None = None,
    cancel_time=None,
):
    """按 broker_order_id 更新订单成交数量/状态(EVENT_ORDER 推送时用)。"""
    if traded is None and status is None and cancel_time is None:
        return
    conn = get_conn()
    try:
        cur = conn.cursor()
        fields, vals = [], []
        if traded is not None:
            fields.append("traded = ?")
            vals.append(traded)
        if status is not None:
            fields.append("status = ?")
            vals.append(status)
        if cancel_time is not None:
            fields.append("cancel_time = ?")
            vals.append(cancel_time)
        vals.append(broker_order_id)
        cur.execute(
            f"UPDATE sim_orders SET {', '.join(fields)} WHERE broker_order_id = ?",
            vals,
        )
    finally:
        conn.close()


def update_order_by_order_id(
    order_id: str,
    traded: int | None = None,
    status: str | None = None,
    cancel_time=None,
):
    """按 order_id(vnpy 内部 id)更新。"""
    if traded is None and status is None and cancel_time is None:
        return
    conn = get_conn()
    try:
        cur = conn.cursor()
        fields, vals = [], []
        if traded is not None:
            fields.append("traded = ?")
            vals.append(traded)
        if status is not None:
            fields.append("status = ?")
            vals.append(status)
        if cancel_time is not None:
            fields.append("cancel_time = ?")
            vals.append(cancel_time)
        vals.append(order_id)
        cur.execute(
            f"UPDATE sim_orders SET {', '.join(fields)} WHERE order_id = ?",
            vals,
        )
    finally:
        conn.close()


def insert_fill(
    account_id: int = 1,
    order_id: str = "",
    stock_code: str = "",
    stock_name: str = "",
    direction: str = "",
    trade_price: float = 0.0,
    trade_volume: int = 0,
    trade_amount: float = 0.0,
    commission: float = 0.0,
    tax: float = 0.0,
    trade_time=None,
    broker: str = "sim",
    broker_trade_id: str = "",
    strategy_name: str = "",
) -> int:
    """写入一笔成交记录,返回 row id。"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sim_fills
            (account_id, order_id, stock_code, stock_name, direction,
             trade_price, trade_volume, trade_amount,
             commission, tax, trade_time, broker, broker_trade_id, strategy_name)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            account_id, order_id, stock_code, stock_name, direction,
            trade_price, trade_volume, trade_amount,
            commission, tax, trade_time, broker, broker_trade_id, strategy_name,
        ))
        return cur.lastrowid
    finally:
        conn.close()


def fetch_orders(account_id: int = 1, day: str | None = None) -> list[dict]:
    """读取订单列表,按 order_time 升序。day 格式 YYYY-MM-DD。"""
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        if day:
            cur.execute(
                "SELECT * FROM sim_orders "
                "WHERE account_id=? AND DATE(order_time)=? "
                "ORDER BY order_time ASC",
                (account_id, day),
            )
        else:
            cur.execute(
                "SELECT * FROM sim_orders "
                "WHERE account_id=? ORDER BY order_time ASC",
                (account_id,),
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def fetch_fills(account_id: int = 1, day: str | None = None) -> list[dict]:
    """读取成交列表,按 trade_time 升序。"""
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        if day:
            cur.execute(
                "SELECT * FROM sim_fills "
                "WHERE account_id=? AND DATE(trade_time)=? "
                "ORDER BY trade_time ASC",
                (account_id, day),
            )
        else:
            cur.execute(
                "SELECT * FROM sim_fills "
                "WHERE account_id=? ORDER BY trade_time ASC",
                (account_id,),
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def fetch_order_fill_timeline(account_id: int = 1, day: str | None = None) -> list[dict]:
    """订单+成交统一时间线(回放用):按时间戳混合排序。

    每条记录带 type='order' 或 type='fill',可直接用于前端回放。
    """
    orders = fetch_orders(account_id, day)
    fills  = fetch_fills(account_id, day)
    timeline = []
    for o in orders:
        timeline.append({
            "type": "order",
            "time": o.get("order_time") or o.get("created_at"),
            "stock_code": o["stock_code"],
            "stock_name": o.get("stock_name", ""),
            "direction": o["direction"],
            "price": o["price"],
            "quantity": o["quantity"],
            "traded": o.get("traded", 0),
            "status": o.get("status", ""),
            "strategy_name": o.get("strategy_name", ""),
            "signal_reason": o.get("signal_reason", ""),
            "raw": o,
        })
    for f in fills:
        timeline.append({
            "type": "fill",
            "time": f.get("trade_time") or f.get("created_at"),
            "stock_code": f["stock_code"],
            "stock_name": f.get("stock_name", ""),
            "direction": f["direction"],
            "price": f["trade_price"],
            "volume": f["trade_volume"],
            "amount": f.get("trade_amount", 0),
            "strategy_name": f.get("strategy_name", ""),
            "raw": f,
        })
    timeline.sort(key=lambda x: x["time"] or "")
    return timeline


# ============================================================
# OmsEngine 事件监听:注册到 vnpy EventEngine
# ============================================================
_oms_listeners_registered = False


def _on_order(event):
    """监听 EVENT_ORDER:将 vnpy OrderData 持久化到 sim_orders。"""
    from vnpy.trader.object import OrderData
    order: OrderData = event.data
    # 映射 vnpy status -> 文本
    status_map = {
        "SUBMITTING": "SUBMITTING",
        "SUBMITTED": "SUBMITTED",
        "PART_TRADED": "PART_TRADED",
        "ALL_TRADED": "ALL_TRADED",
        "CANCELLED": "CANCELLED",
        "CANCELED": "CANCELLED",
        "REJECTED": "REJECTED",
    }
    vt_order_id = order.vt_order_id or ""
    broker_order_id = order.trade_id or order.vt_order_id or ""  # 实盘委托号
    status_str = status_map.get(str(order.status), str(order.status))

    # 尝试更新已有记录(ORDER 事件会多次推送同一单)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM sim_orders WHERE order_id=? OR broker_order_id=? LIMIT 1",
            (vt_order_id, broker_order_id),
        )
        existing = cur.fetchone()
        if existing:
            # UPDATE
            cur.execute("""
                UPDATE sim_orders
                SET traded=?, status=?, cancel_time=?
                WHERE id=?
            """, (order.traded, status_str,
                  None if status_str != "CANCELLED" else _now_str(),
                  existing[0]))
        else:
            # INSERT
            direction = "BUY" if order.direction.value == "多" else "SELL"
            offset = str(order.offset) if hasattr(order, "offset") else ""
            insert_order(
                order_id=vt_order_id,
                stock_code=order.vt_symbol or "",
                stock_name="",
                direction=direction,
                offset=offset,
                price=order.price,
                quantity=order.volume,
                traded=order.traded,
                status=status_str,
                order_time=_now_str(),
                broker="qmt" if broker_order_id else "sim",
                broker_order_id=broker_order_id,
            )
    finally:
        conn.close()


def _on_trade(event):
    """监听 EVENT_TRADE:将 vnpy TradeData 持久化到 sim_fills。"""
    from vnpy.trader.object import TradeData
    trade: TradeData = event.data
    vt_order_id = trade.vt_order_id or ""
    broker_trade_id = trade.trade_id or ""
    direction = "BUY" if trade.direction.value == "多" else "SELL"

    conn = get_conn()
    try:
        cur = conn.cursor()
        # 去重:同一 broker_trade_id 不重复写入
        if broker_trade_id:
            cur.execute("SELECT id FROM sim_fills WHERE broker_trade_id=? LIMIT 1", (broker_trade_id,))
            if cur.fetchone():
                return
        insert_fill(
            order_id=vt_order_id,
            stock_code=trade.vt_symbol or "",
            stock_name="",
            direction=direction,
            trade_price=trade.price,
            trade_volume=trade.volume,
            trade_amount=trade.price * trade.volume,
            trade_time=_now_str(),
            broker="qmt" if broker_trade_id else "sim",
            broker_trade_id=broker_trade_id,
        )
        # 同步更新 sim_orders.traded
        cur.execute(
            "UPDATE sim_orders SET traded=traded+? WHERE order_id=?",
            (trade.volume, vt_order_id),
        )
    finally:
        conn.close()


def _now_str() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def register_oms_listeners(event_engine):
    """注册 EVENT_ORDER / EVENT_TRADE 监听(在 build_main_engine 后调用一次)。"""
    global _oms_listeners_registered
    if _oms_listeners_registered:
        return
    event_engine.register("EVENT_ORDER", _on_order)
    event_engine.register("EVENT_TRADE", _on_trade)
    _oms_listeners_registered = True
    logging.getLogger(__name__).info("✓ OmsEngine 事件监听已注册 (EVENT_ORDER / EVENT_TRADE)")


# ============================================================
# 回放工具:按时间线重演订单/成交
# ============================================================
def replay_timeline(account_id: int = 1, day: str | None = None) -> str:
    """生成可读的订单/成交回放文本(用于复盘报告)。"""
    timeline = fetch_order_fill_timeline(account_id, day)
    if not timeline:
        return "(本日无订单/成交记录)"
    lines = [f"📋 订单/成交回放(共 {len(timeline)} 条)"]
    for i, ev in enumerate(timeline, 1):
        t = ev["time"] or "--:--:--"
        code = ev["stock_code"]
        name = ev.get("stock_name", "")
        if ev["type"] == "order":
            direction = ev["direction"]
            price = ev["price"]
            qty  = ev["quantity"]
            status = ev.get("status", "")
            strat = ev.get("strategy_name", "")
            reason = ev.get("signal_reason", "")
            tag = f"[{strat}]" if strat else ""
            reason_str = f" {reason}" if reason else ""
            lines.append(
                f"  {i:3d}. [{t}] 📩 订单 {direction} {code}{' '+name if name else ''} "
                f"{qty}股 @{price:.2f} {tag}{reason_str} → {status}"
            )
        else:  # fill
            direction = ev["direction"]
            price = ev["price"]
            vol = ev.get("volume", 0)
            amount = ev.get("amount", 0)
            lines.append(
                f"  {i:3d}. [{t}] ✅ 成交 {direction} {code}{' '+name if name else ''} "
                f"{vol}股 @{price:.2f} 金额{amount:.0f}元"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    init_tables()


# ============================================================
# 账户资金口径检测与同步(REQ-035)
# ============================================================
def detect_cash_discrepancy(account_id: int = 1) -> dict | None:
    """检测 config.yaml 与 sim_account 表的 initial_cash 是否一致。

    返回 None 表示一致;返回 dict 表示不一致,含以下字段:
      - account_id: 账户 ID
      - config_initial_cash: config.yaml 中的值
      - db_initial_cash: 数据库中的值
      - diff: 差值(config - db)
      - severity: 'warn'(差异 < 20%)或 'error'(差异 >= 20%)
    """
    try:
        from sim.config import get_account_config
    except ImportError:
        # 独立运行时的兜底
        import yaml
        _ROOT = Path(__file__).resolve().parent.parent
        cfg = yaml.safe_load(open(_ROOT / 'config.yaml', encoding='utf-8')) or {}
        key = 'learn' if account_id == 1 else 'real'
        config_cash = float((cfg.get('accounts') or {}).get(key, {}).get('initial_cash', 100000.0))
    else:
        acct_cfg = get_account_config(account_id)
        config_cash = acct_cfg['initial_cash']

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('SELECT initial_cash FROM sim_account WHERE id = ?', (account_id,))
        row = cur.fetchone()
        db_cash = float(row['initial_cash']) if row else None
    except Exception:
        # 表不存在或其他 DB 错误 → 跳过检测
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if db_cash is None:
        # 数据库里没有这条记录,跳过
        return None

    if abs(config_cash - db_cash) < 0.01:
        return None  # 一致

    diff = config_cash - db_cash
    pct = abs(diff / db_cash) if db_cash else 0
    severity = 'error' if pct >= 0.20 else 'warn'

    return {
        'account_id': account_id,
        'config_initial_cash': config_cash,
        'db_initial_cash': db_cash,
        'diff': diff,
        'diff_pct': pct,
        'severity': severity,
    }


def detect_all_accounts_discrepancy() -> list[dict]:
    """检测所有账户(id=1,2)的资金口径一致性。"""
    results = []
    for aid in (1, 2):
        r = detect_cash_discrepancy(aid)
        if r:
            results.append(r)
    return results


def sync_account_initial_cash(account_id: int = 1, source: str = 'config') -> bool:
    """将 initial_cash 从 source（'config' 或 'db'）同步到另一端。
    
    - source='config': 用 config.yaml 的值覆盖数据库
    - source='db':     用数据库的值覆盖 config.yaml（写入 config.local.yaml）
    
    返回 True 表示成功同步。
    """
    discrepancy = detect_cash_discrepancy(account_id)
    if not discrepancy:
        return False  # 本来就一致，无需同步

    import yaml
    from pathlib import Path as _Path
    _PROJECT_ROOT = _Path(__file__).resolve().parent.parent

    if source == 'config':
        # config.yaml 为准，更新数据库
        config_cash = discrepancy['config_initial_cash']
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute('UPDATE sim_account SET initial_cash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                        (config_cash, account_id))
            print(f"  ✓ account_id={account_id} initial_cash 已同步为 ¥{config_cash:,.2f}（来源: config.yaml）")
            return True
        finally:
            conn.close()
    elif source == 'db':
        # 数据库为准，更新 config.local.yaml
        db_cash = discrepancy['db_initial_cash']
        key = 'learn' if account_id == 1 else 'real'
        # 用 sim.config 的 _LOCAL_FILE（已被 monkeypatch 或用户配置）
        try:
            from sim.config import _LOCAL_FILE
            local_file = _LOCAL_FILE
        except ImportError:
            local_file = _PROJECT_ROOT / 'config.local.yaml'
        if local_file.exists():
            local_cfg = yaml.safe_load(open(local_file, encoding='utf-8')) or {}
        else:
            local_cfg = {}
        if 'accounts' not in local_cfg:
            local_cfg['accounts'] = {}
        if key not in local_cfg['accounts']:
            local_cfg['accounts'][key] = {}
        local_cfg['accounts'][key]['initial_cash'] = db_cash
        with open(local_file, 'w', encoding='utf-8') as f:
            yaml.dump(local_cfg, f, allow_unicode=True, default_flow_style=False)
        print(f"  ✓ account_id={account_id} initial_cash 已同步为 ¥{db_cash:,.2f}（来源: 数据库，写入 config.local.yaml）")
        return True
    return False


def format_discrepancy_warning(discrepancy: dict) -> str:
    """将 discrepancy dict 格式化为人类可读的警告文本(用于复盘报告)。"""
    icon = '⚠️' if discrepancy['severity'] == 'warn' else '🚨'
    label = '模拟盘' if discrepancy['account_id'] == 1 else '实盘'
    return (
        f"{icon} **资金口径不一致 [{label}]**\n"
        f"- config.yaml: ¥{discrepancy['config_initial_cash']:,.2f}\n"
        f"- sim_account 表: ¥{discrepancy['db_initial_cash']:,.2f}\n"
        f"- 差异: ¥{discrepancy['diff']:+,.2f} ({discrepancy['diff_pct']*100:+.1f}%)\n"
        f"\n"
        f"> PnL 计算以 config.yaml 为准。若需同步,可运行:\n"
        f"> `python -c \"from sim.db import sync_account_initial_cash; sync_account_initial_cash({discrepancy['account_id']}, source='config')\"`"
    )


# ============================================================
# 账户事件记录(REQ-001: 资金口径变更追踪)
# ============================================================

def record_account_event(
    account_id: int = 1,
    event_type: str = "reset",
    event_date=None,
    old_initial_cash: float | None = None,
    new_initial_cash: float | None = None,
    old_total_value: float | None = None,
    new_total_value: float | None = None,
    reason: str = "",
    source: str = "system",
) -> int:
    """记录一条账户事件到 sim_account_events 表。返回 row id。"""
    from datetime import date
    if event_date is None:
        event_date = date.today()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sim_account_events
            (account_id, event_type, event_date,
             old_initial_cash, new_initial_cash,
             old_total_value, new_total_value,
             reason, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            account_id, event_type, str(event_date),
            old_initial_cash, new_initial_cash,
            old_total_value, new_total_value,
            reason, source,
        ))
        return cur.lastrowid
    finally:
        conn.close()


def fetch_account_events(account_id: int = 1, limit: int = 20) -> list[dict]:
    """获取账户事件历史，按时间倒序。"""
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM sim_account_events WHERE account_id=? ORDER BY created_at DESC LIMIT ?",
            (account_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ============================================================
# 资金口径跳变检测(REQ-001)
# ============================================================

def detect_cash_jump(
    account_id: int = 1,
    current_total_value: float | None = None,
    current_cash: float | None = None,
    threshold_pct: float = 0.50,  # 50% 跳变阈值
) -> dict | None:
    """检测账户资金是否发生跳变(与上一净值日对比)。

    返回 None 表示无跳变;返回 dict 含跳变详情。
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        # 获取上一净值日记录
        cur.execute(
            "SELECT * FROM sim_daily_nav WHERE account_id=? ORDER BY trade_date DESC LIMIT 1",
            (account_id,),
        )
        prev = cur.fetchone()
        if not prev:
            return None  # 无历史记录，无法判断

        prev_total = float(prev["total_value"])
        prev_cash = float(prev["cash"])
        prev_date = prev["trade_date"]

        # 获取当前账户
        cur.execute("SELECT * FROM sim_account WHERE id=?", (account_id,))
        acct = cur.fetchone()
        if not acct:
            return None

        current_total = current_total_value if current_total_value is not None else float(acct["total_value"])
        current_c = current_cash if current_cash is not None else float(acct["cash"])

        # 计算跳变幅度
        total_jump_pct = (current_total - prev_total) / prev_total if prev_total > 0 else 0
        cash_jump_pct = (current_c - prev_cash) / prev_cash if prev_cash > 0 else 0

        # 检查是否超过阈值
        if abs(total_jump_pct) < threshold_pct and abs(cash_jump_pct) < threshold_pct:
            return None  # 无显著跳变

        # 判断跳变类型
        jump_type = "total_value"
        if abs(cash_jump_pct) > abs(total_jump_pct):
            jump_type = "cash"

        severity = "error" if max(abs(total_jump_pct), abs(cash_jump_pct)) >= 1.0 else "warn"

        return {
            "account_id": account_id,
            "prev_date": prev_date,
            "prev_total_value": prev_total,
            "current_total_value": current_total,
            "total_jump_pct": total_jump_pct,
            "prev_cash": prev_cash,
            "current_cash": current_c,
            "cash_jump_pct": cash_jump_pct,
            "jump_type": jump_type,
            "severity": severity,
            "threshold_pct": threshold_pct,
        }
    finally:
        conn.close()


def format_cash_jump_warning(jump: dict) -> str:
    """将跳变检测结果格式化为人类可读的警告文本。"""
    icon = "🚨" if jump["severity"] == "error" else "⚠️"
    label = "学习账户" if jump["account_id"] == 1 else "真实账户"
    return (
        f"{icon} **资金口径跳变检测 [{label}]**\n"
        f"- 上一净值日({jump['prev_date']}): ¥{jump['prev_total_value']:,.2f}\n"
        f"- 当前: ¥{jump['current_total_value']:,.2f}\n"
        f"- 总资产跳变: {jump['total_jump_pct']*100:+.2f}%\n"
        f"- 现金跳变: {jump['cash_jump_pct']*100:+.2f}%\n"
        f"- 阈值: {jump['threshold_pct']*100:.0f}%\n"
        f"\n"
        f"> 跨日收益率对比已暂停。请确认资金变化原因后，\n"
        f"> 运行 `python -c \"from sim.db import record_account_event; ...\"` 记录事件。"
    )
