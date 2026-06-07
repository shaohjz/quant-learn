#!/usr/bin/env python3
"""
止盈监控脚本 (REQ-019)

监控持仓中浮盈超过止盈线的股票，到达止盈线时自动部分卖出锁定利润。

功能：
1. 从 config.yaml 读取 take_profit_pct 参数
2. 连接 sim_live_mirror.db 查询所有持仓
3. 计算每只票的浮盈 pnl_pct
4. 如果 pnl_pct >= take_profit_pct，生成卖出信号
5. 调用 broker.sell() 执行分批止盈（每次卖 1/3 仓位）
6. 写日志到 output/stop_profit.log
"""

import sys
import os
import yaml
import logging
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from broker.sim_broker import SimBroker
from sim.engine import SimEngine


def setup_logging():
    """配置日志记录"""
    output_dir = project_root / "output"
    output_dir.mkdir(exist_ok=True)
    
    log_file = output_dir / "stop_profit.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


def load_config():
    """加载配置文件"""
    config_path = project_root / "config.yaml"
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_positions_from_db(account_id=1):
    """从数据库获取持仓信息"""
    db_path = project_root / "data" / "sim_live_mirror.db"
    
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # 查询所有持仓（quantity > 0）
    cursor.execute("""
        SELECT stock_code, stock_name, quantity, avg_cost, current_price, 
               market_value, pnl, pnl_pct
        FROM sim_positions 
        WHERE account_id = ? AND quantity > 0
    """, (account_id,))
    
    positions = []
    for row in cursor.fetchall():
        positions.append({
            'stock_code': row[0],
            'stock_name': row[1],
            'quantity': row[2],
            'avg_cost': row[3],
            'current_price': row[4],
            'market_value': row[5],
            'pnl': row[6],
            'pnl_pct': row[7]
        })
    
    conn.close()
    return positions


def calculate_position_value(positions):
    """计算持仓总市值"""
    return sum(p['market_value'] for p in positions)


def execute_stop_profit(sell_orders, broker, logger):
    """执行止盈卖出"""
    results = []
    
    for order in sell_orders:
        stock_code = order['stock_code']
        stock_name = order['stock_name']
        quantity = order['quantity']
        current_price = order['current_price']
        pnl_pct = order['pnl_pct']
        
        try:
            # REQ-058: 使用标准化 signal_reason 格式
            from sim.sell_signal_audit import build_sell_signal_reason
            _sr = build_sell_signal_reason(
                'take_profit', trigger_price=current_price, volume=quantity,
                extra=f'浮盈{pnl_pct:.1%}',
            )
        except Exception:
            _sr = f'take_profit|触发价{current_price:.3f}|量能{quantity}|浮盈{pnl_pct:.1%}'
        try:
            # 调用 broker.sell() 执行卖出
            result = broker.sell(
                stock_code=stock_code,
                price=current_price,
                quantity=quantity,
                stock_name=stock_name,
                signal_reason=_sr,
                signal_detail={
                    "signal": "SELL",
                    "trigger_type": "risk",
                    "triggered_rules": [{"rule": f"止盈（浮盈 {pnl_pct:.2%})", "indicator": "pnl_pct", "current_value": round(pnl_pct, 2), "threshold": round(take_profit_pct * 100, 1), "operator": ">="}],
                    "strategy_version": "stop_profit_monitor/v1.0",
                    "price_snapshot": {"close": round(current_price, 4)},
                },
            )
            
            if result.success:
                logger.info(f"✅ 止盈成功: {stock_name}({stock_code}) 卖出 {quantity}股 @ {current_price:.2f}, 浮盈: {pnl_pct:.2%}")
                results.append({
                    'stock_code': stock_code,
                    'success': True,
                    'quantity': quantity,
                    'price': current_price,
                    'pnl_pct': pnl_pct
                })
            else:
                logger.warning(f"⚠️ 止盈失败: {stock_name}({stock_code}) - {result.msg}")
                results.append({
                    'stock_code': stock_code,
                    'success': False,
                    'msg': result.msg
                })
                
        except Exception as e:
            logger.error(f"❌ 止盈异常: {stock_name}({stock_code}) - {str(e)}")
            results.append({
                'stock_code': stock_code,
                'success': False,
                'msg': str(e)
            })
    
    return results


def main():
    """主函数"""
    logger = setup_logging()
    logger.info("=" * 60)
    logger.info("开始执行止盈监控 (REQ-019)")
    logger.info("=" * 60)
    
    # 1. 加载配置
    try:
        config = load_config()
        take_profit_pct = config['risk']['take_profit_pct']
        logger.info(f"读取配置: take_profit_pct = {take_profit_pct:.2%}")
    except Exception as e:
        logger.error(f"加载配置失败: {e}")
        return
    
    # 2. 获取持仓
    try:
        positions = get_positions_from_db()
        logger.info(f"获取到 {len(positions)} 个持仓")
    except Exception as e:
        logger.error(f"获取持仓失败: {e}")
        return
    
    if not positions:
        logger.info("无持仓，退出")
        return
    
    # 3. 检查止盈条件
    sell_orders = []
    
    for pos in positions:
        stock_code = pos['stock_code']
        stock_name = pos['stock_name']
        quantity = pos['quantity']
        pnl_pct = pos['pnl_pct']
        
        if pnl_pct >= take_profit_pct:
            # 计算卖出数量（1/3 仓位）
            sell_quantity = max(100, int(quantity / 3 / 100) * 100)  # 至少100股，按手数取整
            
            logger.info(f"🎯 触发止盈: {stock_name}({stock_code})")
            logger.info(f"   持仓: {quantity}股, 浮盈: {pnl_pct:.2%}, 止盈线: {take_profit_pct:.2%}")
            logger.info(f"   计划卖出: {sell_quantity}股 (1/3仓位)")
            
            sell_orders.append({
                'stock_code': stock_code,
                'stock_name': stock_name,
                'quantity': sell_quantity,
                'current_price': pos['current_price'],
                'pnl_pct': pnl_pct
            })
    
    # 4. 执行止盈卖出
    if sell_orders:
        logger.info(f"共 {len(sell_orders)} 只股票触发止盈，开始执行卖出...")
        
        # 初始化 broker
        broker = SimBroker(account_id=1)
        broker.connect()
        
        results = execute_stop_profit(sell_orders, broker, logger)
        
        # 统计结果
        success_count = sum(1 for r in results if r['success'])
        logger.info(f"止盈执行完成: 成功 {success_count}/{len(results)}")
        
        broker.disconnect()
    else:
        logger.info("无持仓触发止盈条件")
    
    logger.info("=" * 60)
    logger.info("止盈监控执行完成")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()