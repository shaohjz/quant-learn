#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
post_market_review.py — 收盘复盘（15:05）

生成当日收盘复盘报告，推送到企微群。

用法：
    cd C:/Users/Administrator/.openclaw/workspace/quant-learn
    python scripts/post_market_review.py
"""

import sys
from pathlib import Path

# 必须先设置Python路径，再导入项目模块
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT))

import json
import yaml
import urllib.request
from datetime import datetime, date as Date

# 现在可以安全导入sim模块
from sim.db import get_conn
from sim.realtime_price import get_latest_prices


def push_to_wecom(content: str) -> bool:
    """推送内容到企微群机器人"""
    try:
        # 从config.local.yaml读取webhook URL
        local_cfg = ROOT / "config.local.yaml"
        if not local_cfg.exists():
            print("⚠️ 未找到 config.local.yaml，跳过 webhook 推送")
            return False
            
        data = yaml.safe_load(local_cfg.read_text(encoding="utf-8")) or {}
        webhook_url = (data.get("notifier") or {}).get("wecom_webhook")
        
        if not webhook_url:
            print("⚠️ 未配置 wecom_webhook，跳过 webhook 推送")
            return False
        
        # 构建markdown消息
        body = json.dumps({
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }).encode("utf-8")
        
        req = urllib.request.Request(
            webhook_url, 
            data=body,
            headers={"Content-Type": "application/json"}
        )
        
        resp = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
        ok = '"errcode":0' in resp
        
        if ok:
            print("✅ webhook 推送成功")
        else:
            print(f"⚠️ webhook 返回异常: {resp}")
            
        return ok
        
    except Exception as e:
        print(f"❌ webhook 推送失败: {e}")
        return False


def generate_review_report() -> str:
    """生成收盘复盘报告"""
    today = Date.today().isoformat()
    now = datetime.now().strftime("%H:%M")
    
    conn = get_conn()
    try:
        # 读取账户信息
        acct = conn.execute(
            "SELECT id, account_name, cash, total_value, initial_cash "
            "FROM sim_account WHERE id = 1"
        ).fetchone()
        
        if not acct:
            return f"⚠️ **收盘复盘** {today} {now}\n\n账户不存在，请检查数据库。"
        
        cash = acct["cash"]
        total_value = acct["total_value"]
        initial_cash = acct["initial_cash"] or 20000
        pnl = total_value - initial_cash
        pnl_pct = (pnl / initial_cash * 100) if initial_cash else 0
        
        # 读取持仓
        positions = conn.execute("""
            SELECT stock_code, stock_name, quantity, avg_cost, current_price,
                   market_value, pnl, pnl_pct
            FROM sim_positions
            WHERE account_id = 1 AND quantity > 0
            ORDER BY market_value DESC
        """).fetchall()
        
        # 读取今日交易
        trades = conn.execute("""
            SELECT direction, stock_code, stock_name, price, quantity,
                   amount, signal_reason, created_at
            FROM sim_trades
            WHERE account_id = 1 AND trade_date = ?
            ORDER BY created_at ASC
        """, (today,)).fetchall()
        
        # 构建报告
        lines = []
        lines.append(f"## 📊 收盘复盘 {today} {now}")
        lines.append("")
        
        # 账户概况
        lines.append("### 💰 账户概况")
        lines.append(f"- 总资产: ¥{total_value:,.2f}")
        lines.append(f"- 现金: ¥{cash:,.2f}")
        lines.append(f"- 初始资金: ¥{initial_cash:,.2f}")
        lines.append(f"- 盈亏: ¥{pnl:,.2f} ({pnl_pct:+.2f}%)")
        lines.append("")
        
        # 持仓情况
        if positions:
            lines.append("### 📈 持仓情况")
            for pos in positions:
                code = pos["stock_code"]
                name = pos["stock_name"]
                qty = pos["quantity"]
                cost = pos["avg_cost"]
                price = pos["current_price"]
                mkt_val = pos["market_value"]
                pos_pnl = pos["pnl"]
                pos_pnl_pct = pos["pnl_pct"]
                
                emoji = "🟢" if pos_pnl >= 0 else "🔴"
                lines.append(f"{emoji} **{name}** ({code})")
                lines.append(f"   - 持仓: {qty}股 @ ¥{cost:.2f}")
                lines.append(f"   - 现价: ¥{price:.2f} | 市值: ¥{mkt_val:,.2f}")
                lines.append(f"   - 盈亏: ¥{pos_pnl:,.2f} ({pos_pnl_pct:+.2f}%)")
                lines.append("")
        else:
            lines.append("### 📈 持仓情况")
            lines.append("（无持仓）")
            lines.append("")
        
        # 今日交易
        if trades:
            lines.append("### 🔄 今日交易")
            buy_trades = [t for t in trades if t["direction"] == "BUY"]
            sell_trades = [t for t in trades if t["direction"] == "SELL"]
            
            if buy_trades:
                lines.append("**买入**:")
                for t in buy_trades:
                    lines.append(f"   - {t['stock_name']} ({t['stock_code']}) @ ¥{t['price']:.2f} × {t['quantity']}股")
                    lines.append(f"     原因: {t['signal_reason']}")
            
            if sell_trades:
                lines.append("**卖出**:")
                for t in sell_trades:
                    lines.append(f"   - {t['stock_name']} ({t['stock_code']}) @ ¥{t['price']:.2f} × {t['quantity']}股")
                    lines.append(f"     原因: {t['signal_reason']}")
            
            lines.append("")
        else:
            lines.append("### 🔄 今日交易")
            lines.append("（无交易）")
            lines.append("")
        
        # 提醒
        lines.append("### ⏰ 提醒")
        lines.append("- 15:30 将生成完整复盘报告")
        lines.append("- 请检查持仓止损止盈情况")
        
        return "\n".join(lines)
        
    finally:
        conn.close()


def main():
    """主函数"""
    report = generate_review_report()
    print(report)
    
    # 推送到企微
    push_to_wecom(report)


if __name__ == '__main__':
    main()