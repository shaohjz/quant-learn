"""
每日快照脚本 - 记录账户资产状态
用途: 记录每日收盘后的账户资产，为收益率曲线提供数据
"""
import sqlite3
import sys
from pathlib import Path
from datetime import date
from typing import Dict, Iterable

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sim_live_mirror.db"

# 直接执行脚本时保证能 import 项目内模块
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fetch_close_prices(codes: Iterable[str]) -> Dict[str, float]:
    """获取持仓股票的最新/收盘价。

    daily snapshot 是收盘后资产曲线的输入，因此这里优先使用项目现有
    sim.realtime_price 网关；该网关会先取新浪最新价，并在缺失时用
    baostock 最近日线作为非实时后退。任何行情异常都不应阻断快照保存，
    调用方会继续回退到数据库 current_price / avg_cost。
    """
    clean_codes = [str(c).zfill(6) for c in codes if c]
    if not clean_codes:
        return {}

    try:
        from sim.realtime_price import get_latest_prices_with_fallback

        raw = get_latest_prices_with_fallback(clean_codes)
    except Exception as exc:  # pragma: no cover - 保护定时任务不中断
        print(f"⚠ 获取收盘价失败，使用数据库价格回退: {exc}")
        return {}

    prices: Dict[str, float] = {}
    for code, data in (raw or {}).items():
        try:
            price = float(data.get("price") or 0)
        except (TypeError, ValueError, AttributeError):
            price = 0
        if price > 0:
            prices[str(code).zfill(6)] = price
    return prices


def _choose_position_price(row, close_prices: Dict[str, float]) -> tuple[float, str]:
    """为单个持仓选择估值价格，返回 (price, source)。"""
    code = str(row["stock_code"]).zfill(6)
    if close_prices.get(code, 0) > 0:
        return close_prices[code], "market_close"

    current_price = float(row["current_price"] or 0) if "current_price" in row.keys() else 0
    if current_price > 0:
        return current_price, "db_current_price"

    avg_cost = float(row["avg_cost"] or 0)
    return avg_cost, "avg_cost_fallback"


def get_account_snapshot(conn, account_type='sim'):
    """获取账户快照数据"""
    # 获取现金
    cash_row = conn.execute(
        "SELECT cash FROM sim_account WHERE id=1"
    ).fetchone()
    cash = cash_row[0] if cash_row else 0

    conn.row_factory = sqlite3.Row

    # 获取持仓总市值
    positions = conn.execute(
        """
        SELECT stock_code, quantity, avg_cost, current_price
        FROM sim_positions
        WHERE account_id=1 AND quantity > 0
        """
    ).fetchall()

    close_prices = _fetch_close_prices([p["stock_code"] for p in positions])

    total_market_value = 0
    price_sources = {"market_close": 0, "db_current_price": 0, "avg_cost_fallback": 0}
    for row in positions:
        price, source = _choose_position_price(row, close_prices)
        price_sources[source] = price_sources.get(source, 0) + 1
        total_market_value += int(row["quantity"] or 0) * price

    total_asset = cash + total_market_value
    position_count = len(positions)

    return {
        'total_asset': total_asset,
        'total_market_value': total_market_value,
        'cash': cash,
        'position_count': position_count,
        'price_sources': price_sources,
    }


def save_snapshot(snapshot_date=None):
    """保存每日快照"""
    if snapshot_date is None:
        snapshot_date = date.today().isoformat()

    conn = sqlite3.connect(str(DB_PATH))

    try:
        # 获取快照数据
        snapshot = get_account_snapshot(conn, 'sim')

        # 插入或更新
        conn.execute("""
            INSERT INTO daily_snapshot (
                snapshot_date, account_type, total_asset,
                total_market_value, cash, position_count
            ) VALUES (?, 'sim', ?, ?, ?, ?)
            ON CONFLICT(snapshot_date) DO UPDATE SET
                total_asset=excluded.total_asset,
                total_market_value=excluded.total_market_value,
                cash=excluded.cash,
                position_count=excluded.position_count,
                created_at=CURRENT_TIMESTAMP
        """, (
            snapshot_date,
            snapshot['total_asset'],
            snapshot['total_market_value'],
            snapshot['cash'],
            snapshot['position_count']
        ))

        conn.commit()

        sources = snapshot.get('price_sources', {})
        source_text = ", ".join(f"{k}={v}" for k, v in sources.items() if v)

        print(f"✅ 快照已保存: {snapshot_date}")
        print(f"   总资产: {snapshot['total_asset']:.2f}")
        print(f"   现金: {snapshot['cash']:.2f}")
        print(f"   市值: {snapshot['total_market_value']:.2f}")
        print(f"   持仓数: {snapshot['position_count']}")
        if source_text:
            print(f"   价格来源: {source_text}")

    except Exception as e:
        print(f"❌ 保存快照失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

    return True


if __name__ == '__main__':
    # 可以通过命令行参数指定日期: python snapshot_daily.py 2026-05-25
    snapshot_date = sys.argv[1] if len(sys.argv) > 1 else None
    save_snapshot(snapshot_date)
