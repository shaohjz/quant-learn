import warnings; warnings.warn("This module is DEPRECATED and will be removed. See legacy/README.md for migration.", DeprecationWarning, stacklevel=2)
#!/usr/bin/env python3
"""测试自动交易流程（实际执行）"""
import sqlite3
import sys
from pathlib import Path
from datetime import date

ROOT = Path("C:/Users/Administrator/.openclaw/workspace/quant-learn")
sys.path.insert(0, str(ROOT))

from scripts.auto_trader_v3 import AutoTrader

def setup_test_signal():
    """设置测试信号"""
    print("1. 设置测试信号...")
    
    conn = sqlite3.connect(str(ROOT / "data" / "sim_live_mirror.db"))
    cur = conn.cursor()
    
    # 插入一个测试信号（使用低价股票 600130 波导股份）
    today = date.today().isoformat()
    cur.execute("""
        INSERT OR REPLACE INTO threshold_state
        (stock_code, stock_name, rule_name, rule_threshold,
         first_hit_date, first_hit_price, status, fired_today)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, ("600130", "波导股份", "test_buy", 4.5, today, 4.5, "triggered", 1))
    
    conn.commit()
    conn.close()
    
    print("   ✓ 测试信号已插入（600130 波导股份，阈值 ¥4.5）")

def run_auto_trader():
    """运行自动交易执行器"""
    print("\n2. 运行自动交易执行器（实际执行模式）...")
    
    trader = AutoTrader(account_id=1, dry_run=False)
    trader.run_once()
    
    print("   ✓ 自动交易执行器运行完成")

def check_test_result():
    """检查测试结果"""
    print("\n3. 检查测试结果...")
    
    conn = sqlite3.connect(str(ROOT / "data" / "sim_live_mirror.db"))
    cur = conn.cursor()
    
    # 检查是否有新的交易记录
    cur.execute("""
        SELECT id, stock_code, stock_name, direction, price, quantity, signal_reason
        FROM sim_trades
        WHERE stock_code = '600130'
          AND trade_date = ?
        ORDER BY id DESC
        LIMIT 1
    """, (date.today().isoformat(),))
    
    row = cur.fetchone()
    
    if row:
        print(f"   ✓ 发现交易记录:")
        print(f"      ID: {row[0]}")
        print(f"      股票: {row[1]} ({row[2]})")
        print(f"      方向: {row[3]}")
        print(f"      价格: ¥{row[4]:.4f}")
        print(f"      数量: {row[5]} 股")
        print(f"      信号原因: {row[6]}")
    else:
        print("   ✗ 未发现交易记录")
    
    conn.close()

def cleanup_test_data():
    """清理测试数据"""
    print("\n4. 清理测试数据...")
    
    conn = sqlite3.connect(str(ROOT / "data" / "sim_live_mirror.db"))
    cur = conn.cursor()
    
    # 删除测试信号
    cur.execute("DELETE FROM threshold_state WHERE stock_code = '600130' AND rule_name = 'test_buy'")
    
    # 删除测试交易记录
    cur.execute("DELETE FROM sim_trades WHERE stock_code = '600130' AND signal_reason LIKE '%test_buy%'")
    
    # 删除测试持仓
    cur.execute("DELETE FROM sim_positions WHERE stock_code = '600130'")
    
    conn.commit()
    conn.close()
    
    print("   ✓ 测试数据已清理")

def main():
    """主函数"""
    print("=" * 60)
    print("测试自动交易流程（实际执行）")
    print("=" * 60)
    
    try:
        # 1. 设置测试信号
        setup_test_signal()
        
        # 2. 运行自动交易执行器
        run_auto_trader()
        
        # 3. 检查测试结果
        check_test_result()
        
    finally:
        # 4. 清理测试数据
        cleanup_test_data()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    main()