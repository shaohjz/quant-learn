#!/usr/bin/env python
"""
scripts/notify_auction.py — 集合竞价快报（9:24 运行）

功能：
  - 盘前 9:24 运行，读取实盘持仓 + 阈值规则
  - 获取当前竞价行情（新浪实时）
  - 生成企微 Markdown 格式的集合竞价快报
  - 通过 Webhook 直接推送，不依赖大模型

用法：
  python scripts/notify_auction.py              # 正常推送
  python scripts/notify_auction.py --dry-run     # 只打印，不推送
  python scripts/notify_auction.py --stdout      # 打印到 stdout 并推送

依赖：
  - config.local.yaml 或环境变量 WECOM_WEBHOOK_URL
  - data/sim_live_mirror.db（通过 QUANT_DB_PATH 环境变量）
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

# 设置数据库路径
os.environ.setdefault("QUANT_DB_PATH", str(ROOT / "data" / "sim_live_mirror.db"))

from wecom_webhook import push_markdown, get_webhook_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ====================================================================
#  数据源
# ====================================================================
def get_sina_prices(codes):
    """获取新浪实时行情（同 daily_advisor.py 中的实现）"""
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
                        'name': parts[0],
                        'price': current_price,
                        'open': float(parts[1]) if parts[1] else 0,
                        'yclose': yclose,
                        'high': float(parts[4]) if parts[4] else 0,
                        'low': float(parts[5]) if parts[5] else 0,
                        'volume': float(parts[8]) if parts[8] else 0,
                        'amount': float(parts[9]) if parts[9] else 0,
                        'pct': pct,
                    }
                except (ValueError, IndexError):
                    continue
    return prices


def load_real_positions():
    """加载实盘持仓"""
    import yaml
    path = ROOT / "config_real.yaml"
    if not path.exists():
        return {}, []
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    return data.get('account', {}), data.get('positions', [])


def load_sim_positions():
    """加载模拟盘持仓"""
    conn = sqlite3.connect(str(ROOT / "data" / "sim_live_mirror.db"))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM sim_positions WHERE account_id=1 AND quantity > 0"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_sim_account():
    """加载模拟盘账户"""
    conn = sqlite3.connect(str(ROOT / "data" / "sim_live_mirror.db"))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM sim_account WHERE id=1").fetchone()
    conn.close()
    return dict(row) if row else {}


def load_alert_rules():
    """从 portfolio_alert.py 加载阈值规则（硬编码的表）"""
    # 直接从 portfolio_alert.py 导入 RULES
    sys.path.insert(0, str(ROOT / "scripts"))
    from portfolio_alert import RULES
    return RULES


# ====================================================================
#  消息生成
# ====================================================================
def generate_auction_brief(now: datetime) -> str:
    """生成集合竞价快报 Markdown"""
    today = now.strftime("%Y-%m-%d")
    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]

    lines = []
    lines.append(f"# ⚡ 集合竞价快报 | {today} {weekday_cn}")
    lines.append("")

    # --- 实盘持仓 ---
    real_acc, real_pos = load_real_positions()
    if real_pos:
        codes = [p['code'] for p in real_pos]
        rt = get_sina_prices(codes)
        lines.append("## 💼 实盘持仓")
        lines.append("")
        lines.append("| 代码 | 名称 | 现价 | 涨跌幅 | 昨收 | 竞价量 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for p in real_pos:
            code = p['code']
            d = rt.get(code, {})
            price = d.get('price', 0)
            pct = d.get('pct', 0)
            yclose = d.get('yclose', 0)
            vol = d.get('volume', 0)
            name = d.get('name', p.get('name', ''))
            lines.append(f"| {code} | {name} | ¥{price:.3f} | {pct:+.2f}% | ¥{yclose:.3f} | {vol:.0f} |")
        lines.append("")

    # --- 模拟盘持仓 ---
    sim_pos = load_sim_positions()
    if sim_pos:
        codes = [p['stock_code'] for p in sim_pos]
        rt = get_sina_prices(codes)
        lines.append("## 📊 模拟盘持仓")
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
            lines.append(f"| {code} | {p['stock_name']} | {p['quantity']} | ¥{p['avg_cost']:.3f} | ¥{price:.3f} | {emoji} ¥{pnl:+.0f} ({pnl_pct:+.1f}%) |")
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
            if not d:
                continue
            cur_price = d['price']
            if cur_price <= 0:
                continue
            if r['dir'] == 'below' and cur_price <= r['trigger']:
                triggered.append(r)
            elif r['dir'] == 'above' and cur_price >= r['trigger']:
                triggered.append(r)

        if triggered:
            lines.append("## 🔔 竞价触发提醒")
            lines.append("")
            for r in triggered:
                arrow = "↓" if r['dir'] == 'below' else "↑"
                lines.append(f"**{r['name']}** ({r['code']}) 现价 ¥{rt_all[r['code']]['price']:.2f} {arrow} 阈值 ¥{r['trigger']:.2f}")
                lines.append(f"> {r['message']}")
                lines.append("")
    except Exception as e:
        logger.warning(f"阈值检查失败: {e}")

    # --- 账户总览 ---
    sim_acc = load_sim_account()
    if sim_acc:
        lines.append("## 📈 模拟盘总览")
        lines.append("")
        lines.append(f"- 总资产: ¥{sim_acc['total_value']:,.2f}")
        lines.append(f"- 现金: ¥{sim_acc['cash']:,.2f}")
        lines.append(f"- 起始资金: ¥{sim_acc.get('initial_cash', 100000):,.2f}")
        total_return = (sim_acc['total_value'] / sim_acc.get('initial_cash', 100000) - 1) * 100
        lines.append(f"- 累计收益: {total_return:+.2f}%")
        lines.append("")

    lines.append("---")
    lines.append(f"_⏰ {now.strftime('%H:%M')} 自动生成 | 纯代码推送_")
    return "\n".join(lines)


# ====================================================================
#  主入口
# ====================================================================
def main():
    parser = argparse.ArgumentParser(description="集合竞价快报推送")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不推送")
    parser.add_argument("--stdout", action="store_true", help="同时打印到 stdout")
    parser.add_argument("--no-webhook", action="store_true", help="不推送企微")
    args = parser.parse_args()

    now = datetime.now()
    logger.info(f"=== 集合竞价快报 {now.strftime('%Y-%m-%d %H:%M')} ===")

    # 检查是否交易日（周末跳过）
    if now.weekday() >= 5:
        msg = f"📴 非交易日 ({now.strftime('%A')})，跳过"
        print(msg)
        logger.info(msg)
        return 0

    content = generate_auction_brief(now)

    if args.stdout or args.dry_run:
        print(content)
        print(f"\n{'='*60}")
        print(f"Webhook URL: {'已配置' if get_webhook_url() else '未配置'}")

    if not args.dry_run and not args.no_webhook:
        ok = push_markdown(content)
        if ok:
            logger.info("✅ 集合竞价快报推送成功")
        else:
            logger.warning("⚠️ 推送失败（已打印到 stdout）")
            print(content)
    elif args.dry_run:
        logger.info("🔍 Dry-run 模式，未推送")

    logger.info("=== 集合竞价快报 完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
