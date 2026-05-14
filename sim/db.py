"""
sim/db.py
MySQL 连接模块，复用 market-analysis 的连接配置。
"""
import pymysql

DB_CONFIG = {
    "unix_socket": "/tmp/mysql.sock",
    "user": "root",
    "password": "",
    "database": "market_analysis",
    "charset": "utf8mb4",
    "autocommit": True,
}


def get_conn():
    return pymysql.connect(**DB_CONFIG)


def init_tables():
    """创建模拟交易相关的表并初始化默认账户"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 模拟账户
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sim_account (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    account_name VARCHAR(50) DEFAULT 'default',
                    initial_cash DECIMAL(12,2) DEFAULT 100000.00,
                    cash DECIMAL(12,2) DEFAULT 100000.00,
                    total_value DECIMAL(12,2) DEFAULT 100000.00,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            """)

            # 模拟持仓
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sim_positions (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    account_id INT DEFAULT 1,
                    stock_code VARCHAR(10),
                    stock_name VARCHAR(50),
                    quantity INT DEFAULT 0,
                    avg_cost DECIMAL(10,4),
                    current_price DECIMAL(10,4),
                    market_value DECIMAL(12,2),
                    pnl DECIMAL(12,2),
                    pnl_pct DECIMAL(8,4),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            """)

            # 交易记录
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sim_trades (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    account_id INT DEFAULT 1,
                    trade_date DATE,
                    stock_code VARCHAR(10),
                    stock_name VARCHAR(50),
                    direction VARCHAR(4),
                    price DECIMAL(10,4),
                    quantity INT,
                    amount DECIMAL(12,2),
                    commission DECIMAL(8,2),
                    tax DECIMAL(8,2),
                    signal_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 每日净值
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sim_daily_nav (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    account_id INT DEFAULT 1,
                    trade_date DATE,
                    total_value DECIMAL(12,2),
                    cash DECIMAL(12,2),
                    market_value DECIMAL(12,2),
                    daily_return DECIMAL(8,4),
                    cumulative_return DECIMAL(8,4),
                    max_drawdown DECIMAL(8,4),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_date (account_id, trade_date)
                )
            """)

            # 初始化默认账户（如果不存在）
            cur.execute("SELECT id FROM sim_account WHERE id = 1")
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO sim_account (id, account_name, initial_cash, cash, total_value)
                    VALUES (1, 'default', 100000.00, 100000.00, 100000.00)
                """)
                print("  ✓ 默认账户已创建（10万资金）")
            else:
                print("  ✓ 默认账户已存在")

        print("  ✓ 所有表已创建/确认")
    finally:
        conn.close()


if __name__ == "__main__":
    init_tables()
