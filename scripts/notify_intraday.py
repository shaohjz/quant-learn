#!/usr/bin/env python
"""
scripts/notify_intraday.py — 盘中盯盘（盘中每 30 分钟运行）

功能：
  - 盘中每 30 分钟运行（9:30/10:00/.../14:30）
  - 读取实盘 + 模拟盘持仓，获取实时行情
  - 检查阈值触发（同 portfolio_alert.py 的逻辑）
  - 生成企微 Markdown 格式的盘中盯盘报告
  - 通过 Webhook 直接推送，不依赖大模型

与 portfolio_alert.py 的区别：
  - notify_intraday.py 是纯推送脚本，不保存 alert_state
  - 每次运行独立检查，不依赖历史状态
  - 消息格式为企微 Markdown（更美观）

用法：
  python scripts/notify_intraday.py              # 正常推送
  python scripts/notify_intraday.py --dry-run     # 只打印，不推送
  python scripts/notify_intraday.py --force       # 强制运行（忽略交易时段检查）
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


def load_alert_rules():
    sys.path.insert(0, str(ROOT / "scripts"))
    from portfolio_alert import RULES
    return RULES


def in_trade_hours(now: datetime) -> bool:
    """A股盘中交易时段：9:30-11:30 / 13:00-15:00"""
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (dtime(9, 30) <= t <= dtime(11, 30)) or (dtime(13, 0) <= t <= dtime(15, 0))


# ====================================================================
#  消息生成
# ====================================================================
def generate_intraday_watch(now: datetime) -> str:
    """生成盘中盯盘 Markdown"""
    today = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    lines = []
    lines.append(f"# 👁️ 盘中盯盘 | {today} {time_str}")
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
            lines.append(f"- {emoji} **{name}** ({code}) ¥{price:.3f} ({pct:+.2f}%) | 成本¥{cost:.3f} | {qty}股 | 浮盈¥{pnl:+.0f}({pnl_pct:+.1f}%)")
        lines.append("")

    # --- 模拟盘持仓 ---
    sim_pos = load_sim_positions()
    if sim_pos:
        codes = [p['stock_code'] for p in sim_pos]
        rt = get_sina_prices(codes)
        lines.append("## 📈 模拟盘持仓")
        lines.append("")
        for p in sim_pos:
            code = p['stock_code']
            d = rt.get(code, {})
            price = d.get('price', p['current_price'])
            pct = d.get('pct', 0)
            pnl = (price - p['avg_cost']) * p['quantity']
            pnl_pct = (price - p['avg_cost']) / p['avg_cost'] * 100
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"- {emoji} **{p['stock_name']}** ({code}) ¥{price:.3f} ({pct:+.2f}%) | {p['quantity']}股 | 浮盈¥{pnl:+.0f}({pnl_pct:+.1f}%)")
        lines.append("")

    # --- 阈值触发检查 ---
    try:
        rules = load_alert_rules()
        all_codes = list({r['code'] for r in rules})
        rt_all = get_sina_prices(all_codes)
        triggered = []
        for r in rules:
            code = r['code']
            d = rt_all.get(code)
            if not d or d['price'] <= 0:
                continue
            if r['dir'] == 'below' and d['price'] <= r['trigger']:
                triggered.append(r)
            elif r['dir'] == 'above' and d['price'] >= r['trigger']:
                triggered.append(r)

        if triggered:
            lines.append("## 🔔 阈值触发")
            lines.append("")
            for r in triggered:
                arrow = "↓" if r['dir'] == 'below' else "↑"
                lines.append(f"**{r['name']}** ({r['code']}) 现价 ¥{rt_all[r['code']]['price']:.2f} {arrow} 阈值 ¥{r['trigger']:.2f}")
                lines.append(f"> {r['message']}")
                lines.append("")
        else:
            lines.append("## ✅ 状态")
            lines.append("")
            lines.append("当前无阈值触发，各标的运行正常。")
            lines.append("")
    except Exception as e:
        logger.warning(f"阈值检查失败: {e}")

    lines.append("---")
    lines.append(f"_⏰ {time_str} 自动生成 | 纯代码推送_")
    return "\n".join(lines)


# ====================================================================
#  主入口
# ====================================================================
def main():
    parser = argparse.ArgumentParser(description="盘中盯盘推送")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不推送")
    parser.add_argument("--stdout", action="store_true", help="同时打印到 stdout")
    parser.add_argument("--no-webhook", action="store_true", help="不推送企微")
    parser.add_argument("--force", action="store_true", help="强制运行（忽略交易时段检查）")
    args = parser.parse_args()

    now = datetime.now()
    logger.info(f"=== 盘中盯盘 {now.strftime('%Y-%m-%d %H:%M')} ===")

    # 交易时段检查
    if not args.force and not in_trade_hours(now):
        msg = f"📴 非交易时段 ({now.strftime('%H:%M %A')})，跳过"
        print(msg)
        logger.info(msg)
        return 0

    content = generate_intraday_watch(now)

    if args.stdout or args.dry_run:
        print(content)
        print(f"\n{'='*60}")
        print(f"Webhook URL: {'已配置' if get_webhook_url() else '未配置'}")

    if not args.dry_run and not args.no_webhook:
        ok = push_markdown(content)
        if ok:
            logger.info("✅ 盘中盯盘推送成功")
        else:
            logger.warning("⚠️ 推送失败（已打印到 stdout）")
            print(content)

    logger.info("=== 盘中盯盘 完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
