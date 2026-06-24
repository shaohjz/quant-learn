#!/usr/bin/env python3
"""
scripts/auto_trader.py — 自动交易执行器

功能：
  - 监听新生成的信号（从 sim_trades 表或 threshold_state 表）
  - 当 auto_trade 配置为 true 时，立即执行交易
  - 支持买入和卖出信号
  - 记录执行日志

使用：
  python scripts/auto_trader.py              # 执行一次
  python scripts/auto_trader.py --daemon    # 守护进程模式（每5分钟检查一次）
  python scripts/auto_trader.py --dry-run    # 干运行（不实际执行交易）
"""
import sys
import os
import json
import logging
import argparse
import time
from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Optional

# 添加项目根目录到路径
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.config import load_config, get_account_config
from sim.engine import SimEngine
from sim.signal_generator import generate_signals, dedupe_signals

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(str(ROOT / "logs" / "auto_trader.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 确保日志目录存在
(ROOT / "logs").mkdir(exist_ok=True)

class AutoTrader:
    """自动交易执行器"""
    
    def __init__(self, account_id: int = 1, dry_run: bool = False):
        """初始化自动交易执行器
        
        Args:
            account_id: 账户ID
            dry_run: 是否干运行（不实际执行交易）
        """
        self.account_id = account_id
        self.dry_run = dry_run
        self.engine = SimEngine(account_id)
        self.config = load_config()
        self.account_config = get_account_config(account_id)
        
        # 检查是否启用自动交易
        self.auto_trade = self.account_config.get("auto_trade", False)
        if not self.auto_trade:
            logger.warning(f"账户 {account_id} 未启用自动交易 (auto_trade=false)")
        
        logger.info(f"自动交易执行器初始化完成 (账户: {account_id}, 自动交易: {self.auto_trade}, 干运行: {dry_run})")
    
    def check_new_signals(self) -> List[Dict]:
        """检查新生成的信号
        
        Returns:
            新信号列表
        """
        # TODO: 实现信号检测逻辑
        # 可以从以下来源检测新信号：
        # 1. threshold_state 表（阈值触发信号）
        # 2. sim_trades 表（新生成的交易信号）
        # 3. strategy_shadow_signals 表（策略影子信号）
        
        logger.info("检查新信号...")
        new_signals = []
        
        # 示例：从 threshold_state 表检测新触发的阈值信号
        try:
            import sqlite3
            db_path = ROOT / "data" / "sim_live_mirror.db"
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            
            # 查询今天新触发的阈值信号（status='triggered' 且今天首次触发）
            today = date.today().isoformat()
            cur.execute("""
                SELECT id, stock_code, stock_name, rule_name, rule_threshold,
                       first_hit_date, first_hit_price, status
                FROM threshold_state
                WHERE status = 'triggered'
                  AND first_hit_date = ?
                  AND fired_today = 1
            """, (today,))
            
            rows = cur.fetchall()
            for row in rows:
                signal = {
                    "source": "threshold",
                    "id": row["id"],
                    "stock_code": row["stock_code"],
                    "stock_name": row["stock_name"],
                    "rule_name": row["rule_name"],
                    "rule_threshold": row["rule_threshold"],
                    "trigger_date": row["first_hit_date"],
                    "trigger_price": row["first_hit_price"],
                    "signal_type": "buy",  # 阈值触发通常是买入信号
                }
                new_signals.append(signal)
                logger.info(f"发现新信号: {signal['stock_code']} ({signal['stock_name']}) - {signal['rule_name']}")
            
            conn.close()
        except Exception as e:
            logger.error(f"检查新信号失败: {e}")
        
        logger.info(f"发现 {len(new_signals)} 个新信号")
        return new_signals
    
    def execute_buy_signal(self, signal: Dict) -> bool:
        """执行买入信号
        
        Args:
            signal: 买入信号字典
            
        Returns:
            是否执行成功
        """
        if not self.auto_trade:
            logger.warning("自动交易未启用，跳过买入信号")
            return False
        
        stock_code = signal["stock_code"]
        stock_name = signal.get("stock_name", "")
        trigger_price = signal.get("trigger_price", 0)
        
        # 获取当前价格（使用触发价或实时价）
        current_price = trigger_price
        if current_price <= 0:
            logger.error(f"无效的触发价: {current_price}")
            return False
        
        # 计算买入数量（根据仓位管理策略）
        quantity = self.calculate_buy_quantity(stock_code, current_price)
        if quantity <= 0:
            logger.warning(f"买入数量计算为0，跳过: {stock_code}")
            return False
        
        # 构建信号原因
        signal_reason = f"auto_trade|{signal.get('rule_name', 'unknown')}|触发价{signal.get('trigger_price', 0):.3f}"
        
        if self.dry_run:
            logger.info(f"[DRY RUN] 买入 {stock_name or stock_code} {quantity}股 @ {current_price:.4f}")
            return True
        
        # 执行买入
        try:
            result = self.engine.buy(
                stock_code=stock_code,
                price=current_price,
                quantity=quantity,
                stock_name=stock_name,
                signal_reason=signal_reason,
                broker="sim"
            )
            
            if result["success"]:
                logger.info(f"✓ 买入成功: {result['msg']}")
                return True
            else:
                logger.error(f"✗ 买入失败: {result['msg']}")
                return False
        except Exception as e:
            logger.error(f"✗ 买入异常: {e}")
            return False
    
    def execute_sell_signal(self, signal: Dict) -> bool:
        """执行卖出信号
        
        Args:
            signal: 卖出信号字典
            
        Returns:
            是否执行成功
        """
        if not self.auto_trade:
            logger.warning("自动交易未启用，跳过卖出信号")
            return False
        
        stock_code = signal["stock_code"]
        stock_name = signal.get("stock_name", "")
        trigger_price = signal.get("trigger_price", 0)
        
        # 获取当前持仓
        positions = self.engine.get_positions()
        position = None
        for pos in positions:
            if pos["stock_code"] == stock_code:
                position = pos
                break
        
        if not position:
            logger.warning(f"无持仓，跳过卖出信号: {stock_code}")
            return False
        
        # 计算卖出数量（根据止盈/止损策略）
        quantity = self.calculate_sell_quantity(position, signal)
        if quantity <= 0:
            logger.warning(f"卖出数量计算为0，跳过: {stock_code}")
            return False
        
        # 构建信号原因
        signal_reason = f"auto_trade|{signal.get('rule_name', 'unknown')}|触发价{signal.get('trigger_price', 0):.3f}"
        
        if self.dry_run:
            logger.info(f"[DRY RUN] 卖出 {stock_name or stock_code} {quantity}股 @ {trigger_price:.4f}")
            return True
        
        # 执行卖出
        try:
            result = self.engine.sell(
                stock_code=stock_code,
                price=trigger_price,
                quantity=quantity,
                stock_name=stock_name,
                signal_reason=signal_reason,
                broker="sim"
            )
            
            if result["success"]:
                logger.info(f"✓ 卖出成功: {result['msg']}")
                return True
            else:
                logger.error(f"✗ 卖出失败: {result['msg']}")
                return False
        except Exception as e:
            logger.error(f"✗ 卖出异常: {e}")
            return False
    
    def calculate_buy_quantity(self, stock_code: str, price: float) -> int:
        """计算买入数量
        
        Args:
            stock_code: 股票代码
            price: 买入价格
            
        Returns:
            买入数量（股）
        """
        # 获取账户信息
        account = self.engine.get_account()
        available_cash = account["cash"]
        
        # 仓位管理策略（根据 REQ-066 需求描述）
        # 建议单只仓位上限 15-20%，持仓 5-8 只
        max_position_pct = 0.15  # 15% 单只仓位上限
        max_position_value = available_cash * max_position_pct
        
        # 计算最大可买数量（向下取整到100股）
        max_quantity = int(max_position_value / price / 100) * 100
        
        # 检查是否已持有该股票
        positions = self.engine.get_positions()
        current_position_value = 0
        for pos in positions:
            if pos["stock_code"] == stock_code:
                current_position_value = pos["market_value"]
                break
        
        # 如果已持有，考虑加仓（但不超过上限）
        if current_position_value > 0:
            available_position_value = max_position_value - current_position_value
            if available_position_value <= 0:
                logger.info(f"已达仓位上限，不加仓: {stock_code}")
                return 0
            max_quantity = int(available_position_value / price / 100) * 100
        
        # 确保至少有足够的现金买入100股
        min_quantity = 100
        if max_quantity < min_quantity:
            logger.warning(f"现金不足，无法买入100股: {stock_code} (可用现金: {available_cash:.2f})")
            return 0
        
        return max_quantity
    
    def calculate_sell_quantity(self, position: Dict, signal: Dict) -> int:
        """计算卖出数量
        
        Args:
            position: 持仓信息
            signal: 卖出信号
            
        Returns:
            卖出数量（股）
        """
        # 根据 REQ-066 需求描述：
        # 止盈自动执行：浮盈 ≥30% 时自动卖出 50%，≥50% 时卖出剩余
        
        stock_code = position["stock_code"]
        quantity = position["quantity"]
        avg_cost = position["avg_cost"]
        current_price = signal.get("trigger_price", position["current_price"])
        
        if avg_cost <= 0:
            return quantity  # 保守起见，全部卖出
        
        pnl_pct = (current_price - avg_cost) / avg_cost
        
        # 止盈策略
        if pnl_pct >= 0.50:  # 浮盈 ≥50%
            return quantity  # 卖出剩余
        elif pnl_pct >= 0.30:  # 浮盈 ≥30%
            return quantity // 2  # 卖出50%
        else:
            # 可能不是止盈信号，而是止损信号，卖出全部
            return quantity
    
    def run_once(self):
        """执行一次自动交易检查"""
        logger.info("=" * 60)
        logger.info("开始自动交易检查")
        logger.info("=" * 60)
        
        if not self.auto_trade:
            logger.warning("自动交易未启用，跳过")
            return
        
        # 1. 检查新信号
        new_signals = self.check_new_signals()
        
        if not new_signals:
            logger.info("无新信号")
            return
        
        # 2. 执行信号
        for signal in new_signals:
            try:
                if signal.get("signal_type") == "buy":
                    self.execute_buy_signal(signal)
                elif signal.get("signal_type") == "sell":
                    self.execute_sell_signal(signal)
                else:
                    logger.warning(f"未知信号类型: {signal.get('signal_type')}")
            except Exception as e:
                logger.error(f"执行信号失败: {signal}, 错误: {e}")
        
        logger.info("=" * 60)
        logger.info("自动交易检查完成")
        logger.info("=" * 60)
    
    def run_daemon(self, interval_seconds: int = 300):
        """运行守护进程模式
        
        Args:
            interval_seconds: 检查间隔（秒），默认5分钟
        """
        logger.info(f"启动守护进程模式（间隔: {interval_seconds}秒）")
        
        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"自动交易检查异常: {e}")
            
            logger.info(f"等待 {interval_seconds} 秒后继续...")
            time.sleep(interval_seconds)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="自动交易执行器")
    parser.add_argument("--account", type=int, default=1, help="账户ID（默认: 1）")
    parser.add_argument("--daemon", action="store_true", help="守护进程模式（每5分钟检查一次）")
    parser.add_argument("--interval", type=int, default=300, help="守护进程模式检查间隔（秒，默认: 300）")
    parser.add_argument("--dry-run", action="store_true", help="干运行（不实际执行交易）")
    args = parser.parse_args()
    
    # 创建自动交易执行器
    trader = AutoTrader(account_id=args.account, dry_run=args.dry_run)
    
    # 运行
    if args.daemon:
        trader.run_daemon(interval_seconds=args.interval)
    else:
        trader.run_once()

if __name__ == "__main__":
    main()