#!/usr/bin/env python
"""
scripts/notify_review.py — 收盘复盘（15:05 运行）+ 日终总结（15:10 运行）

功能：
  - 收盘后 15:05 运行：生成收盘复盘
  - 15:10 运行：生成日终总结（含净值、交易、持仓变化）
  - 读取实盘 + 模拟盘持仓、当日交易、净值
  - 生成企微 Markdown 格式的复盘报告
  - 通过 Webhook 直接推送，不依赖大模型

用法：
  python scripts/notify_review.py [--mode review|summary] [--date YYYY-MM-DD]
  --mode review:  收盘复盘（15:05）
  --mode summary: 日终总结（15:10，默认）

  python scripts/notify_review.py --dry-run     # 只打印，不推送
"""
import os
import sys
import json
import logging
import argparse
import sqlite3
from pathlib import Path
from datetime import datetime, date, time as dtime, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

os.environ.setdefault("QUANT_DB_PATH", str(ROOT / "data" / "sim_live_mirror.db"))

from wecom_webhook import push_markdown, get_webhook_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ====================================================================
#  数据源
# ====================================================================
def get_sina_prices(codes):
    if not codes:
        return {}
    import re as _re
    import urllib.request
    sina_codes = []
    for c in codes:
        prefix = 'sh' if c.startswith(('60', '68', '11', '5')) else 'sz'
        sina_codes.append(prefix + c)
    url = 'https://hq.sinajs.cn/list=' + ','.join(sina_codes)
    headers = {'Referer': 'https://finance.sina.com.cn'}
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10)
        text = r.read().decode('gbk')
    except Exception as e:
        logger.warning(f"新浪行情拉取失败: {e}")
        return {}
    prices = {}
    for line in text.strip().split('\n'):
        m = _re.search(r'hq_str_(s[hz])(\d+)="(.+?)"', line)
        if m:
            parts = m.group(3).split(',')
            if len(parts) >= 10 and parts[3]:
                code = m.group(2)
                try:
                    current_price = float(parts[3])
                    yclose = float(parts[2])
                    if current_price == 0 and yclose > 0:
                        current_price = yclose
                    pct = round((current_price - yclose) / yclose * 100, 2) if yclose > 0 else 0.0
                    prices[code] = {
                        'name': parts[0], 'price': current_price, 'open': float(parts[1]) if parts[1] else 0,
                        'yclose': yclose, 'high': float(parts[4]) if parts[4] else 0,
                        'low': float(parts[5]) if parts[5] else 0, 'volume': float(parts[8]) if parts[8] else 0,
                        'amount': float(parts[9]) if parts[9] else 0, 'pct': pct,
                    }
                except (ValueError, IndexError):
                    continue
    return prices


def load_real_positions():
    import yaml
    path = ROOT / "config_real.yaml"
    if not path.exists():
        return {}, []
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    return data.get('account', {}), data.get('positions', [])


def load_sim_positions():
    conn = sqlite3.connect(str(ROOT / "data" / "sim_live_mirror.db"))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM sim_positions WHERE account_id=1 AND quantity > 0").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_sim_account():
    conn = sqlite3.connect(str(ROOT / "data" / "sim_live_mirror.db"))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM sim_account WHERE id=1").fetchone()
    conn.close()
    return dict(row) if row else {}


def load_trades_by_date(target_date):
    conn = sqlite3.connect(str(ROOT / "data" / "sim_live_mirror.db"))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM sim_trades WHERE account_id=1 AND trade_date=? ORDER BY created_at",
        (target_date.isoformat(),)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_daily_nav(target_date):
    conn = sqlite3.connect(str(ROOT / "data" / "sim_live_mirror.db"))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM sim_daily_nav WHERE account_id=1 ORDER BY trade_date DESC LIMIT 5"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_alert_rules():
    sys.path.insert(0, str(ROOT / "scripts"))
    from portfolio_alert import RULES
    return RULES


def load_alert_state(target_date):
    """读取当日阈值触发记录"""
    state_file = ROOT / "output" / "alert_state.json"
    if not state_file.exists():
        return []
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        today_state = state.get(target_date.isoformat(), {})
        triggered = []
        for rule_id, info in today_state.items():
            triggered.append({
                "rule_id": rule_id,
                "triggered_at": info.get("triggered_at", ""),
                "price": info.get("price", 0),
                "trigger": info.get("trigger", 0),
            })
        return triggered
    except Exception as e:
        logger.warning(f"读取 alert_state 失败: {e}")
        return []


# ====================================================================
#  消息生成
# ====================================================================
def generate_review(now: datetime, target_date: date) -> str:
    """生成收盘复盘 Markdown"""
    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][target_date.weekday()]

    lines = []
    lines.append(f"# 🌆 收盘复盘 | {target_date.isoformat()} {weekday_cn}")
    lines.append("")

    # --- 实盘持仓 ---
    real_acc, real_pos = load_real_positions()
    if real_pos:
        codes = [p['code'] for p in real_pos]
        rt = get_sina_prices(codes)
        lines.append("## 💼 实盘持仓")
        lines.append("")
        for p in real_pos:
            code = p['code']
            d = rt.get(code, {})
            price = d.get('price', 0)
            pct = d.get('pct', 0)
            cost = p.get('avg_cost', 0)
            qty = p.get('quantity', 0)
            pnl = (price - cost) * qty if price and cost else 0
            pnl_pct = (price - cost) / cost * 100 if cost > 0 else 0
            emoji = "🟢" if pnl >= 0 else "🔴"
            name = d.get('name', p.get('name', ''))
            lines.append(f"- {emoji} **{name}** ({code}) 收¥{price:.3f} ({pct:+.2f}%) | 成本¥{cost:.3f} | {qty}股 | 浮盈¥{pnl:+.0f}({pnl_pct:+.1f}%)")
        lines.append("")

    # --- 模拟盘持仓 ---
    sim_pos = load_sim_positions()
    if sim_pos:
        codes = [p['stock_code'] for p in sim_pos]
        rt = get_sina_prices(codes)
        lines.append("## 📈 模拟盘收盘")
        lines.append("")
        for p in sim_pos:
            code = p['stock_code']
            d = rt.get(code, {})
            price = d.get('price', p['current_price'])
            pct = d.get('pct', 0)
            pnl = (price - p['avg_cost']) * p['quantity']
            pnl_pct = (price - p['avg_cost']) / p['avg_cost'] * 100
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"- {emoji} **{p['stock_name']}** ({code}) 收¥{price:.3f} ({pct:+.2f}%) | {p['quantity']}股 | 浮盈¥{pnl:+.0f}({pnl_pct:+.1f}%)")
        lines.append("")

    # --- 当日交易 ---
    trades = load_trades_by_date(target_date)
    if trades:
        lines.append("## 🤖 当日交易")
        lines.append("")
        for t in trades:
            arrow = "🟢 BUY" if t['direction'] == 'BUY' else "🔴 SELL"
            lines.append(f"- {arrow} {t['stock_name']} {t['quantity']}股 @¥{t['price']:.2f} | {t.get('signal_reason', '')[:40]}")
        lines.append("")
    else:
        lines.append("## 🤖 当日交易")
        lines.append("")
        lines.append("_当日无虚拟交易_")
        lines.append("")

    # --- 阈值触发 ---
    alerts = load_alert_state(target_date)
    if alerts:
        lines.append("## 🔔 阈值触发")
        lines.append("")
        for a in alerts:
            lines.append(f"- **{a['rule_id']}** @{a['triggered_at']} 价¥{a['price']:.2f} 阈值¥{a['trigger']:.2f}")
        lines.append("")

    lines.append("---")
    lines.append(f"_⏰ {now.strftime('%H:%M')} 自动生成 | 纯代码推送_")
    return "\n".join(lines)


def generate_summary(now: datetime, target_date: date) -> str:
    """生成日终总结 Markdown"""
    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][target_date.weekday()]

    lines = []
    lines.append(f"# 📋 日终总结 | {target_date.isoformat()} {weekday_cn}")
    lines.append("")

    # --- 账户总览 ---
    sim_acc = load_sim_account()
    if sim_acc:
        total_return = (sim_acc['total_value'] / sim_acc.get('initial_cash', 100000) - 1) * 100
        lines.append("## 📊 账户总览")
        lines.append("")
        lines.append(f"- **总资产**: ¥{sim_acc['total_value']:,.2f}")
        lines.append(f"- **现金**: ¥{sim_acc['cash']:,.2f}")
        lines.append(f"- **累计收益**: {total_return:+.2f}%")
        lines.append("")

    # --- 持仓概览 ---
    sim_pos = load_sim_positions()
    if sim_pos:
        codes = [p['stock_code'] for p in sim_pos]
        rt = get_sina_prices(codes)
        lines.append("## 💼 持仓概览")
        lines.append("")
        lines.append("| 代码 | 名称 | 数量 | 成本 | 现价 | 盈亏 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for p in sim_pos:
            code = p['stock_code']
            d = rt.get(code, {})
            price = d.get('price', p['current_price'])
            pnl = (price - p['avg_cost']) * p['quantity']
            pnl_pct = (price - p['avg_cost']) / p['avg_cost'] * 100
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"| {code} | {p['stock_name']} | {p['quantity']} | ¥{p['avg_cost']:.3f} | ¥{price:.3f} | {emoji} {pnl_pct:+.1f}% |")
        lines.append("")

    # --- 当日交易 ---
    trades = load_trades_by_date(target_date)
    if trades:
        lines.append("## 🤖 当日交易")
        lines.append("")
        for t in trades:
            arrow = "🟢 BUY" if t['direction'] == 'BUY' else "🔴 SELL"
            lines.append(f"- {arrow} {t['stock_name']} {t['quantity']}股 @¥{t['price']:.2f}")
        lines.append("")

    # --- 净值 ---
    navs = load_daily_nav(target_date)
    if navs:
        lines.append("## 📉 近期净值")
        lines.append("")
        lines.append("| 日期 | 总资产 | 当日 | 累计 |")
        lines.append("| --- | --- | --- | --- |")
        for n in navs[:5]:
            dr = n.get('daily_return') or 0
            cr = n.get('cumulative_return') or 0
            tv = n.get('total_value') or 0
            lines.append(f"| {n['trade_date']} | ¥{tv:,.2f} | {dr:+.2f}% | {cr:+.2f}% |")
        lines.append("")

    lines.append("---")
    lines.append(f"_⏰ {now.strftime('%H:%M')} 自动生成 | 纯代码推送_")
    return "\n".join(lines)


# ====================================================================
#  主入口
# ====================================================================
def main():
    parser = argparse.ArgumentParser(description="收盘复盘/日终总结推送")
    parser.add_argument("--mode", choices=["review", "summary"], default="summary",
                        help="review=收盘复盘(15:05), summary=日终总结(15:10)")
    parser.add_argument("--date", type=str, default=None, help="复盘日期 YYYY-MM-DD（默认今日）")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不推送")
    parser.add_argument("--stdout", action="store_true", help="同时打印到 stdout")
    parser.add_argument("--no-webhook", action="store_true", help="不推送企微")
    args = parser.parse_args()

    now = datetime.now()
    target_date = date.fromisoformat(args.date) if args.date else date.today()

    logger.info(f"=== {'收盘复盘' if args.mode == 'review' else '日终总结'} {now.strftime('%Y-%m-%d %H:%M')} ===")

    if target_date.weekday() >= 5:
        print(f"📴 非交易日 ({target_date.strftime('%A')})，跳过")
        return 0

    if args.mode == "review":
        content = generate_review(now, target_date)
    else:
        content = generate_summary(now, target_date)

    if args.stdout or args.dry_run:
        print(content)
        print(f"\n{'='*60}")
        print(f"Webhook URL: {'已配置' if get_webhook_url() else '未配置'}")

    if not args.dry_run and not args.no_webhook:
        ok = push_markdown(content)
        if ok:
            logger.info(f"✅ {'收盘复盘' if args.mode == 'review' else '日终总结'}推送成功")
        else:
            logger.warning("⚠️ 推送失败（已打印到 stdout）")
            print(content)

    logger.info(f"=== {'收盘复盘' if args.mode == 'review' else '日终总结'} 完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
