#!/usr/bin/env python
"""
scripts/daily_advisor.py — 每日实盘操作建议生成器

根据持仓 + 观察列表 + 市场状态，自动生成分时段操作建议：
  1. 盘前(8:30-9:15)   — 复盘昨日 + 今日策略规划
  2. 竞价(9:15-9:25)   — 竞价观察要点 + 挂单建议
  3. 盘中(9:30-14:00)  — 阈值触发 + 操作信号
  4. 尾盘(14:30-15:00) — 收盘前决策
  5. 盘后(15:00+)      — 复盘总结

使用：
  python scripts/daily_advisor.py [--phase pre|auction|intraday|closing|review|auto]
  --phase auto: 根据当前时间自动判断阶段
  
推送: 通过企微 webhook 推送
"""
import sys
import yaml
import json
import sqlite3
import logging
import argparse
import urllib.request
import re
from pathlib import Path
from datetime import datetime, date, time as dtime, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = ROOT / "data" / "sim_live_mirror.db"

# ====================================================================
#  配置加载
# ====================================================================
def load_config():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding='utf-8'))
    auto_cfg = {}
    auto_path = ROOT / "config_auto.yaml"
    if auto_path.exists():
        auto_cfg = yaml.safe_load(auto_path.read_text(encoding='utf-8')) or {}
    return cfg, auto_cfg

def load_webhook():
    local_cfg = ROOT / "config.local.yaml"
    if local_cfg.exists():
        d = yaml.safe_load(local_cfg.read_text(encoding='utf-8'))
        return (d or {}).get("notifier", {}).get("wecom_webhook", "")
    return ""

def push_webhook(content: str):
    url = load_webhook()
    if not url:
        logger.warning("未配置 webhook")
        return False
    body = json.dumps({"msgtype": "text", "text": {"content": content}}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        logger.error(f"推送失败: {e}")
        return False

# ====================================================================
#  实时行情
# ====================================================================
def get_sina_prices(codes):
    if not codes:
        return {}
    sina_codes = []
    for c in codes:
        prefix = 'sh' if c.startswith(('60', '68', '11', '5')) else 'sz'
        sina_codes.append(prefix + c)
    url = 'https://hq.sinajs.cn/list=' + ','.join(sina_codes)
    headers = {'Referer': 'https://finance.sina.com.cn'}
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10)
        text = r.read().decode('gbk')
    except:
        return {}
    prices = {}
    for line in text.strip().split('\n'):
        m = re.search(r'hq_str_(s[hz])(\d+)="(.+?)"', line)
        if m:
            parts = m.group(3).split(',')
            if len(parts) >= 10 and parts[3]:
                code = m.group(2)
                prices[code] = {
                    'name': parts[0],
                    'price': float(parts[3]),
                    'open': float(parts[1]),
                    'yclose': float(parts[2]),
                    'high': float(parts[4]),
                    'low': float(parts[5]),
                    'volume': float(parts[8]),
                    'amount': float(parts[9]),
                    'pct': round((float(parts[3]) - float(parts[2])) / float(parts[2]) * 100, 2) if float(parts[2]) > 0 else 0,
                }
    return prices

# ====================================================================
#  数据库
# ====================================================================
def get_positions():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM sim_positions WHERE account_id=1 AND quantity > 0"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_account():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM sim_account WHERE id=1").fetchone()
    conn.close()
    return dict(row) if row else {}

def get_recent_trades(days=3):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM sim_trades WHERE account_id=1 AND trade_date >= ? ORDER BY created_at DESC",
        (since,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ====================================================================
#  规则解析
# ====================================================================
def parse_alert_rules(cfg):
    """解析 config.yaml 中的告警规则"""
    rules = []
    watchlist = cfg.get('watchlist', {})
    if isinstance(watchlist, dict):
        stocks = watchlist.get('user_manual', {})
    else:
        stocks = {}
    
    for code, info in stocks.items():
        if not info.get('enabled', True):
            continue
        rules_data = info.get('rules', {})
        if isinstance(rules_data, dict):
            # {level_name: {trigger, dir, msg}} 格式
            for level_name, rule_info in rules_data.items():
                if isinstance(rule_info, dict):
                    rules.append({
                        'code': code,
                        'name': info.get('name', ''),
                        'level': level_name,
                        'trigger': rule_info.get('trigger', 0),
                        'direction': rule_info.get('dir', 'below'),
                    })
        elif isinstance(rules_data, list):
            for rule in rules_data:
                rules.append({
                    'code': code,
                    'name': info.get('name', ''),
                    'level': rule.get('level', ''),
                    'trigger': rule.get('trigger', 0),
                    'direction': rule.get('direction', 'below'),
                })
    return rules

# ====================================================================
#  各阶段建议生成
# ====================================================================
def gen_pre_market(positions, rules, cfg, auto_cfg):
    """盘前建议 (8:30-9:15)"""
    today = date.today().strftime('%m/%d')
    lines = [f"☀️ 盘前操作建议 ({today})", "=" * 40]
    
    # 1. 持仓概览
    lines.append("\n📊 当前持仓:")
    acc = get_account()
    total_mv = sum(p['quantity'] * p.get('avg_cost', 0) for p in positions)
    lines.append(f"  现金: ¥{acc.get('cash', 0):,.0f} | 持仓: {len(positions)} 只 | 仓位: {total_mv/(acc.get('cash',0)+total_mv)*100:.0f}%")
    for p in positions:
        lines.append(f"  • {p['stock_code']} {p.get('stock_name', ''):6s} {p['quantity']}股 @{p['avg_cost']:.2f}")
    
    # 2. 今日关键价位
    lines.append("\n🎯 今日关键价位（买入触发）:")
    buy_rules = [r for r in rules if 'buy' in r['level'] and r['direction'] == 'below']
    buy_rules.sort(key=lambda x: x['trigger'])
    shown = set()
    for r in buy_rules:
        if r['code'] in shown:
            continue
        shown.add(r['code'])
        lines.append(f"  • {r['code']} {r['name']:6s} 触发价 ¥{r['trigger']:.2f} ({r['level']})")
    
    # 3. 止损价位
    lines.append("\n🚨 止损价位（持仓）:")
    for p in positions:
        cost = p['avg_cost']
        stop_8 = round(cost * 0.92, 2)
        # 找 trend_break 规则
        tb_price = None
        for r in rules:
            if r['code'] == p['stock_code'] and 'trend_break' in r['level']:
                tb_price = r['trigger']
                break
        stop = max(tb_price or 0, stop_8)
        lines.append(f"  • {p['stock_code']} {p.get('stock_name', ''):6s} 止损 ¥{stop:.2f} (成本{cost:.2f}, -{(1-stop/cost)*100:.1f}%)")
    
    # 4. 操作策略
    lines.append("\n📝 今日策略:")
    lines.append("  1. 竞价阶段(9:15-9:25): 观察主力集合竞价方向")
    lines.append("  2. 开盘 5 分钟: 不追涨不杀跌，观察量能")
    lines.append("  3. 触发阈值则按交易计划执行（注意盈亏比）")
    lines.append("  4. 下午 2 点后不开新仓（尾盘风险大）")
    
    return '\n'.join(lines)


def gen_auction(positions, rules):
    """竞价建议 (9:15-9:25)"""
    lines = ["🔔 竞价阶段操作建议 (9:15-9:25)", "=" * 40]
    
    # 拉实时行情（竞价期间新浪有数据）
    all_codes = list(set(
        [p['stock_code'] for p in positions] +
        [r['code'] for r in rules]
    ))
    rt = get_sina_prices(all_codes)
    
    # 1. 持仓股竞价表现
    lines.append("\n📈 持仓股竞价动态:")
    for p in positions:
        code = p['stock_code']
        if code in rt:
            d = rt[code]
            pct = d['pct']
            emoji = "🟢" if pct > 0 else "🔴" if pct < 0 else "⚪"
            lines.append(f"  {emoji} {code} {d['name']:6s} 竞价 ¥{d['price']:.2f} ({pct:+.2f}%)")
    
    # 2. 观察股是否接近触发价
    lines.append("\n🎯 观察股触发监测:")
    triggered = []
    close_to = []
    for r in rules:
        if 'buy' not in r['level']:
            continue
        code = r['code']
        if code in rt:
            price = rt[code]['price']
            trigger = r['trigger']
            if price <= trigger:
                triggered.append((code, r['name'], price, trigger, r['level']))
            elif price <= trigger * 1.02:  # 2%内接近
                close_to.append((code, r['name'], price, trigger, r['level']))
    
    if triggered:
        lines.append("  ⚡ 已触发:")
        for code, name, price, trigger, level in triggered:
            lines.append(f"    🔥 {code} {name} ¥{price:.2f} ≤ ¥{trigger:.2f} ({level})")
        lines.append("  → 开盘确认后可按交易计划建仓")
    
    if close_to:
        lines.append("  ⏰ 接近触发:")
        for code, name, price, trigger, level in close_to:
            gap = (price - trigger) / trigger * 100
            lines.append(f"    📍 {code} {name} ¥{price:.2f} (距触发 {gap:.1f}%)")
        lines.append("  → 密切关注，开盘可能触发")
    
    if not triggered and not close_to:
        lines.append("  ✅ 暂无接近触发的观察股")
    
    # 3. 竞价操作建议
    lines.append("\n📝 竞价操作:")
    lines.append("  • 9:15-9:20 可撤单，观察主力试盘方向")
    lines.append("  • 9:20-9:25 不可撤单，如有确定信号可挂单")
    lines.append("  • 持仓股如大幅低开(>3%)，不急卖，等开盘5分钟")
    lines.append("  • 持仓股如大幅高开(>5%)，考虑开盘首笔减半仓")
    
    return '\n'.join(lines)


def gen_intraday(positions, rules):
    """盘中建议 (9:30-14:00)"""
    lines = ["📊 盘中操作建议", "=" * 40]
    
    all_codes = list(set(
        [p['stock_code'] for p in positions] +
        [r['code'] for r in rules]
    ))
    rt = get_sina_prices(all_codes)
    
    # 1. 持仓实时盈亏
    lines.append("\n💰 持仓实时:")
    for p in positions:
        code = p['stock_code']
        cost = p['avg_cost']
        if code in rt:
            price = rt[code]['price']
            pnl_pct = (price - cost) / cost * 100
            pct_today = rt[code]['pct']
            emoji = "🟢" if pnl_pct > 0 else "🔴"
            lines.append(f"  {emoji} {code} {rt[code]['name']:6s} ¥{price:.2f} 今日{pct_today:+.1f}% 浮盈{pnl_pct:+.1f}%")
    
    # 2. 需要操作的信号
    lines.append("\n⚡ 操作信号:")
    action_count = 0
    
    for p in positions:
        code = p['stock_code']
        cost = p['avg_cost']
        if code not in rt:
            continue
        price = rt[code]['price']
        pnl_pct = (price - cost) / cost * 100
        
        # 止损判断
        stop_8 = cost * 0.92
        tb_price = None
        for r in rules:
            if r['code'] == code and 'trend_break' in r['level']:
                tb_price = r['trigger']
                break
        stop = max(tb_price or 0, stop_8)
        
        if price <= stop:
            lines.append(f"  🚨 【止损】{code} {rt[code]['name']} 现价¥{price:.2f} ≤ 止损¥{stop:.2f}")
            lines.append(f"     → 建议立即卖出！亏损 {pnl_pct:.1f}%")
            action_count += 1
        elif pnl_pct >= 15:
            lines.append(f"  🎯 【止盈①】{code} {rt[code]['name']} 盈利 +{pnl_pct:.1f}% 达到止盈①(+15%)")
            lines.append(f"     → 建议卖出 1/2 仓位锁定利润")
            action_count += 1
        elif pnl_pct >= 25:
            lines.append(f"  🎯 【止盈②】{code} {rt[code]['name']} 盈利 +{pnl_pct:.1f}% 达到止盈②(+25%)")
            lines.append(f"     → 建议全部卖出！")
            action_count += 1
    
    # 买入信号
    for r in rules:
        if 'buy' not in r['level']:
            continue
        code = r['code']
        if code in rt and rt[code]['price'] <= r['trigger']:
            # 是否已持有
            held = any(p['stock_code'] == code for p in positions)
            if not held:
                lines.append(f"  💰 【买入】{code} {r['name']} ¥{rt[code]['price']:.2f} ≤ 触发¥{r['trigger']:.2f}")
                lines.append(f"     → {r['level']}，查看交易计划确认盈亏比后执行")
                action_count += 1
    
    if action_count == 0:
        lines.append("  ✅ 暂无需要操作的信号，继续持有")
    
    # 3. 注意事项
    now = datetime.now()
    if now.hour < 10:
        lines.append("\n⏰ 当前早盘，波动大，谨慎操作")
    elif now.hour >= 13 and now.hour < 14:
        lines.append("\n⏰ 午后开盘，关注资金回流方向")
    
    return '\n'.join(lines)


def gen_closing(positions, rules):
    """尾盘建议 (14:00-15:00)"""
    lines = ["🌅 尾盘操作建议 (14:00-15:00)", "=" * 40]
    
    all_codes = [p['stock_code'] for p in positions]
    rt = get_sina_prices(all_codes)
    
    lines.append("\n📊 持仓收盘前状态:")
    for p in positions:
        code = p['stock_code']
        cost = p['avg_cost']
        if code in rt:
            d = rt[code]
            pnl_pct = (d['price'] - cost) / cost * 100
            # 今日振幅
            amp = (d['high'] - d['low']) / d['yclose'] * 100 if d['yclose'] > 0 else 0
            emoji = "🟢" if d['pct'] > 0 else "🔴" if d['pct'] < 0 else "⚪"
            lines.append(f"  {emoji} {code} {d['name']:6s} ¥{d['price']:.2f} 今日{d['pct']:+.1f}% 振幅{amp:.1f}% 浮盈{pnl_pct:+.1f}%")
    
    lines.append("\n📝 尾盘操作原则:")
    lines.append("  • 14:30 后不开新仓（次日风险不可控）")
    lines.append("  • 持仓股尾盘拉升 > 3%: 可考虑减仓 1/3（可能是诱多）")
    lines.append("  • 持仓股尾盘跳水 > 3%: 不恐慌卖出（可能是洗盘）")
    lines.append("  • 关注尾盘集合竞价(14:57-15:00)的量能变化")
    
    # 明日策略预告
    lines.append("\n📅 明日关注:")
    lines.append("  • 检查持仓股是否有重大公告/财报")
    lines.append("  • 观察今日异动股次日走势")
    lines.append("  • 等待 daily_recalibrate 8:25 自动更新阈值")
    
    return '\n'.join(lines)


def gen_review(positions, rules):
    """盘后复盘 (15:00+)"""
    lines = ["📝 盘后复盘", "=" * 40]
    
    all_codes = [p['stock_code'] for p in positions]
    rt = get_sina_prices(all_codes)
    
    # 今日持仓盈亏统计
    total_pnl_today = 0
    lines.append("\n📊 今日持仓表现:")
    for p in positions:
        code = p['stock_code']
        if code in rt:
            d = rt[code]
            day_pnl = (d['price'] - d['yclose']) * p['quantity']
            total_pnl_today += day_pnl
            emoji = "🟢" if d['pct'] > 0 else "🔴" if d['pct'] < 0 else "⚪"
            lines.append(f"  {emoji} {code} {d['name']:6s} {d['pct']:+.1f}% 日盈亏{day_pnl:+.0f}")
    
    lines.append(f"\n  💰 今日总盈亏: ¥{total_pnl_today:+,.0f}")
    
    # 近期交易
    trades = get_recent_trades(3)
    if trades:
        lines.append("\n📋 近3日交易:")
        for t in trades[:5]:
            dir_str = "买" if t['direction'] == 'BUY' else "卖"
            lines.append(f"  {t['trade_date']} {dir_str} {t['stock_code']} {t.get('stock_name', '')} {t['quantity']}股 @{t['price']:.2f}")
    
    # 明日计划
    lines.append("\n📅 明日计划:")
    lines.append("  • 8:25 阈值自动校准 (daily_recalibrate)")
    lines.append("  • 8:30 盘前建议推送 (daily_advisor --phase pre)")
    lines.append("  • 9:15 竞价建议推送 (daily_advisor --phase auction)")
    lines.append("  • 触发则按交易计划执行，不触发则持有不动")
    
    return '\n'.join(lines)

# ====================================================================
#  主入口
# ====================================================================
def determine_phase():
    """根据当前时间自动判断阶段"""
    now = datetime.now()
    t = now.time()
    
    if now.weekday() >= 5:
        return 'review'  # 周末看复盘
    
    if t < dtime(9, 15):
        return 'pre'
    elif t < dtime(9, 30):
        return 'auction'
    elif t < dtime(14, 0):
        return 'intraday'
    elif t < dtime(15, 0):
        return 'closing'
    else:
        return 'review'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['pre', 'auction', 'intraday', 'closing', 'review', 'auto'], default='auto')
    parser.add_argument('--no-webhook', action='store_true')
    args = parser.parse_args()
    
    phase = args.phase if args.phase != 'auto' else determine_phase()
    logger.info(f"生成操作建议: phase={phase}")
    
    cfg, auto_cfg = load_config()
    positions = get_positions()
    rules = parse_alert_rules(cfg)
    
    generators = {
        'pre': lambda: gen_pre_market(positions, rules, cfg, auto_cfg),
        'auction': lambda: gen_auction(positions, rules),
        'intraday': lambda: gen_intraday(positions, rules),
        'closing': lambda: gen_closing(positions, rules),
        'review': lambda: gen_review(positions, rules),
    }
    
    content = generators[phase]()
    print(content)
    
    if not args.no_webhook:
        if push_webhook(content):
            logger.info("✓ 已推送企微")
        else:
            logger.warning("推送失败")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
