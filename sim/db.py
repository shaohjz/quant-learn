"""
sim/db.py
SQLite 持久层 — 跨平台、零配置、单文件。

数据库路径默认在项目根目录的 data/sim.db，可通过环境变量 QUANT_DB_PATH 覆盖。
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


# 默认数据库路径：项目根目录/data/sim.db
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _PROJECT_ROOT / "data" / "sim.db"
DB_PATH = Path(os.environ.get("QUANT_DB_PATH", str(_DEFAULT_DB)))

# 默认初始资金（可通过环境变量覆盖）
DEFAULT_INITIAL_CASH = float(os.environ.get("QUANT_INITIAL_CASH", "10000"))


def _ensure_db_dir():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    """获取一个 SQLite 连接（启用外键，使用 Row 工厂方便按列名取值）。"""
    _ensure_db_dir()
    conn = sqlite3.connect(str(DB_PATH), timeout=30, isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # 写并发更友好
    return conn


@contextmanager
def cursor():
    """上下文管理器写法，少写几行 close。"""
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

        # 索引
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_date ON sim_trades(trade_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_code ON sim_trades(stock_code)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pos_code ON sim_positions(stock_code)")

        # 初始化默认账户（如果不存在）
        cur.execute("SELECT id FROM sim_account WHERE id = 1")
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO sim_account (id, account_name, initial_cash, cash, total_value) "
                "VALUES (1, 'default', ?, ?, ?)",
                (DEFAULT_INITIAL_CASH, DEFAULT_INITIAL_CASH, DEFAULT_INITIAL_CASH),
            )
            print(f"  ✓ 默认账户已创建（初始资金 {DEFAULT_INITIAL_CASH:,.2f}）")
        else:
            print("  ✓ 默认账户已存在")

        print(f"  ✓ 所有表已创建/确认 (DB={DB_PATH})")
    finally:
        conn.close()


if __name__ == "__main__":
    init_tables()
