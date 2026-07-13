"""
sim/float_loss_advisor.py - REQ-026 浮亏风控顾问

分析持仓浮亏状态，生成风控建议。

检查逻辑:
1. 读取 sim_positions 表(account_id=1 学习账户)
2. 按浮亏严重程度分级:
   - critical: 浮亏 >= 8% (接近 -8% 硬止损)
   - warning: 浮亏 >= 5%
   - watch: 浮亏 >= 3%
3. 生成建议:止损/减仓/观察
"""

from dataclasses import dataclass
from typing import List, Optional
from datetime import date


@dataclass
class FloatLossPosition:
    """浮亏持仓信息"""
    code: str
    name: str
    quantity: int
    avg_cost: float
    current_price: float
    pnl_pct: float  # 浮亏百分比(负数)
    severity: str  # 'critical' | 'warning' | 'watch'
    account_id: int
    advice: str  # 建议文本


def check_critical_float_loss(account_id: int = 1, threshold: float = -8.0) -> List[FloatLossPosition]:
    """
    检查严重浮亏持仓(默认 >= -8%)

    Args:
        account_id: 账户ID(1=学习账户, 2=真实账户)
        threshold: 浮亏阈值(负数,如 -8.0 表示 -8%)

    Returns:
        List[FloatLossPosition]: 严重浮亏持仓列表
    """
    try:
        import sqlite3
        from pathlib import Path

        DB_PATH = Path(__file__).resolve().parents[1] / 'data' / 'sim_live_mirror.db'

        if not DB_PATH.exists():
            return []

        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        positions = conn.execute("""
            SELECT stock_code, stock_name, quantity, avg_cost, current_price, pnl_pct
            FROM sim_positions
            WHERE account_id = ? AND quantity > 0 AND pnl_pct <= ?
            ORDER BY pnl_pct ASC
        """, (account_id, threshold)).fetchall()
        conn.close()

        result = []
        for pos in positions:
            pnl_pct = float(pos['pnl_pct'] or 0)
            severity = 'critical' if pnl_pct <= -8 else ('warning' if pnl_pct <= -5 else 'watch')
            advice = _generate_advice(pos['stock_code'], pos['stock_name'],
                                      float(pos['avg_cost'] or 0),
                                      float(pos['current_price'] or 0),
                                      pnl_pct, severity)
            result.append(FloatLossPosition(
                code=pos['stock_code'],
                name=pos['stock_name'],
                quantity=int(pos['quantity']),
                avg_cost=float(pos['avg_cost'] or 0),
                current_price=float(pos['current_price'] or 0),
                pnl_pct=pnl_pct,
                severity=severity,
                account_id=account_id,
                advice=advice
            ))

        return result
    except Exception as e:
        print(f"check_critical_float_loss 异常: {e}")
        return []


def _generate_advice(code: str, name: str, avg_cost: float,
                     current_price: float, pnl_pct: float, severity: str) -> str:
    """生成风控建议"""
    if severity == 'critical':
        return (f"🚨 {name}({code}) 浮亏{pnl_pct:.2f}%,已触发-8%止损线！"
                f"建议立即止损卖出,避免进一步亏损。")
    elif severity == 'warning':
        return (f"⚠️ {name}({code}) 浮亏{pnl_pct:.2f}%,接近止损线。"
                f"建议密切关注,若跌破-8%立即止损。")
    else:
        return (f"👀 {name}({code}) 浮亏{pnl_pct:.2f}%,在观察范围内。"
                f"建议持续跟踪,设置止损预警。")


def format_quick_float_loss_alert(positions: List[FloatLossPosition]) -> Optional[str]:
    """
    格式化浮亏警报(用于企微推送)

    Args:
        positions: 浮亏持仓列表

    Returns:
        Optional[str]: 格式化后的警报文本,无持仓返回 None
    """
    if not positions:
        return None

    alert = f"🚨 浮亏风控警报 ({date.today()})\n"
    alert += "=" * 40 + "\n"

    critical = [p for p in positions if p.severity == 'critical']
    warning = [p for p in positions if p.severity == 'warning']
    watch = [p for p in positions if p.severity == 'watch']

    if critical:
        alert += "\n🔴 严重浮亏(>= -8%):\n"
        for p in critical:
            alert += f"  • {p.name}({p.code}) 浮亏{p.pnl_pct:.2f}% | 成本¥{p.avg_cost:.2f}→现价¥{p.current_price:.2f}\n"
            alert += f"    ⚠️ 建议:立即止损!\n"

    if warning:
        alert += "\n🟡 警告浮亏(>= -5%):\n"
        for p in warning:
            alert += f"  • {p.name}({p.code}) 浮亏{p.pnl_pct:.2f}% | 成本¥{p.avg_cost:.2f}→现价¥{p.current_price:.2f}\n"

    if watch:
        alert += "\n🟢 观察浮亏(>= -3%):\n"
        for p in watch:
            alert += f"  • {p.name}({p.code}) 浮亏{p.pnl_pct:.2f}% | 成本¥{p.avg_cost:.2f}→现价¥{p.current_price:.2f}\n"

    alert += "\n" + "=" * 40 + "\n"
    alert += f"⚠️ 请及时处理,避免亏损扩大!"

    return alert


def check_all_float_loss(account_id: int = 1) -> List[FloatLossPosition]:
    """
    检查所有浮亏持仓(>= -3%)

    Args:
        account_id: 账户ID

    Returns:
        List[FloatLossPosition]: 所有浮亏持仓
    """
    return check_critical_float_loss(account_id=account_id, threshold=-3.0)


if __name__ == '__main__':
    # 测试
    print("检查学习账户浮亏持仓...")
    positions = check_critical_float_loss(account_id=1)
    if positions:
        alert = format_quick_float_loss_alert(positions)
        print(alert)
    else:
        print("无严重浮亏持仓")

    print("\n检查所有浮亏持仓...")
    all_positions = check_all_float_loss(account_id=1)
    print(f"共 {len(all_positions)} 只持仓浮亏")
