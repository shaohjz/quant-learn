"""清理 fix_buyzone_signal_text.py 引入的错误 signal_reason 文案。

问题：fix_buyzone_signal_text.py 把 signal_reason 从 "跌至 X.YZ！接近 MA10(X.YZ)"
     改为 "跌至 44.17（实际成交价），昨日 MA10=57.33"，导致：
     - _check_buy_zone_ma_deviation 从 message 正则提取到的是成交价，偏差恒为0%
     - signal_reason 中同时存在成交价和 MA10，格式混乱

修复：将 signal_reason 统一为 "BuyZone 阈值 {trigger}（{trade_date} MA10={ma10}），试探建仓"
     即 daily_recalibrate.py 生成的标准格式，与 buy_strong 风格一致。
"""

import sqlite3, os, re

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'sim_live_mirror.db')

def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # 查找所有被 fix_buyzone_signal_text.py 改过的记录
    rows = cur.execute("""
        SELECT id, stock_code, stock_name, price, signal_reason, trade_date
        FROM sim_trades
        WHERE account_id=1
          AND signal_reason LIKE '%实际成交价%昨日 MA10=%'
    """).fetchall()

    fixes = []
    for tid, code, name, price, reason, trade_date in rows:
        # 提取昨日 MA10 值
        m = re.search(r'昨日 MA10=([\d.]+)', reason)
        if not m:
            continue
        ma10 = m.group(1)
        # 提取 trigger（MA10 阈值）
        trigger = float(ma10)
        
        # 构造标准格式
        new_reason = f"💰 {name} BuyZone 阈值 {trigger}（{trade_date} MA10={ma10}），试探建仓"
        
        cur.execute(
            "UPDATE sim_trades SET signal_reason=? WHERE id=?",
            (new_reason, tid)
        )
        fixes.append(f"  {code} {name}: '{reason[:40]}...' → 标准格式 (MA10={ma10})")

    conn.commit()
    conn.close()

    print(f"已清理 {len(fixes)} 条信号文案：")
    for f in fixes:
        print(f)

    return len(fixes)

if __name__ == '__main__':
    main()
