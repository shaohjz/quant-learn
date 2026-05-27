#!/usr/bin/env python
"""
scripts/daily_advisor.py — 每日实盘操作建议生成器

根据持仓(实盘+模拟) + 观察列表 + 市场状态，自动生成分时段操作建议：
  1. 盘前(8:30-9:15)   — 复盘昨日 + 今日策略规划
  2. 竞价(9:15-9:25)   — 竞价观察要点 + 挂单建议
  3. 盘中(9:30-14:00)  — 阈值触发 + 操作信号
  4. 尾盘(14:30-15:00) — 收盘前决策
  5. 盘后(15:00+)      — 复盘总结

使用：
  python scripts/daily_advisor.py [--phase pre|auction|intraday|closing|review|auto]
  --phase auto: 根据当前时间自动判断阶段
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

def load_real_positions():
    """加载实盘持仓"""
    path = ROOT / "config_real.yaml"
    if not path.exists():
        return {}, []
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    return data.get('account', {}), data.get('positions', [])

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


def save_push_history(phase: str, content: str, push_type: str = 'advisor'):
    """保存推送记录到数据库"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "INSERT INTO push_history (push_type, phase, content) VALUES (?,?,?)",
            (f"{push_type}_{phase}", phase, content)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

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
                current_price = float(parts[3])
                yclose = float(parts[2])
                if current_price == 0 and yclose > 0:
                    current_price = yclose
                pct = round((current_price - yclose) / yclose * 100, 2) if yclose > 0 else 0.0
                prices[code] = {
                    'name': parts[0],
                    'price': current_price,
                    'open': float(parts[1]),
                    'yclose': yclose,
                    'high': float(parts[4]),
                    'low': float(parts[5]),
                    'volume': float(parts[8]),
                    'amount': float(parts[9]),
                    'pct': pct,
                }
    return prices

# ====================================================================
#  数据库
# ====================================================================
def get_sim_positions():
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
    rules = []
    watchlist = cfg.get('watchlist', {})
    stocks = watchlist.get('user_manual', {}) if isinstance(watchlist, dict) else {}
    
    for code, info in stocks.items():
        if not info.get('enabled', True):
            continue
        rules_data = info.get('rules', {})
        if isinstance(rules_data, dict):
            for level_name, rule_info in rules_data.items():
                if isinstance(rule_info, dict):
                    rules.append({
                        'code': code,
                        'name': info.get('name', ''),
                        'level': level_name,
                        'trigger': rule_info.get('trigger', 0),
                        'direction': rule_info.get('dir', 'below'),
                        'msg': rule_info.get('msg', ''),
                        'source': info.get('source', ''),
                        'added_reason': info.get('added_reason', ''),
                        'tags': info.get('tags', []),
                        'auto_buy_disabled': info.get('auto_buy_disabled', False),
                    })
    return rules


def get_stock_context(code: str, rules_for_code: list, cur_price: float) -> dict:
    """汇总一只股的所有阈值 → 计算 MA 位置参考、距离、是否同时破位等"""
    ctx = {'ma10': None, 'ma20': None, 'trend_break': None, 'all_levels': []}
    for r in rules_for_code:
        ctx['all_levels'].append(r['level'])
        # 从 msg 中提取 MA 信息，启发式
        if r['level'] == 'buy_zone':
            ctx['ma10'] = r['trigger']  # 约定：buy_zone = MA10
        elif r['level'] == 'buy_strong':
            ctx['ma20'] = r['trigger']  # 约定：buy_strong = MA20
        elif r['level'] == 'trend_break':
            ctx['trend_break'] = r['trigger']
    return ctx

# ====================================================================
#  实盘持仓分析
# ====================================================================
def gen_real_section(rt_prices, phase=''):
    """生成实盘持仓分析段落"""
    real_acc, real_pos = load_real_positions()
    if not real_pos:
        return ""
    
    lines = ["", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
             "💼 【实盘持仓】", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    
    total_mv = 0
    total_pnl = 0
    for p in real_pos:
        code = p['code']
        cost = p['avg_cost']
        qty = p['quantity']
        if code in rt_prices:
            d = rt_prices[code]
            price = d['price']
            pnl = (price - cost) * qty
            pnl_pct = (price - cost) / cost * 100
            pct_today = d['pct']
            total_mv += price * qty
            total_pnl += pnl
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"  {emoji} {code} {p['name']:6s} {qty}股 成本{cost:.3f} 现价{price:.3f} 今日{pct_today:+.1f}% 浮盈{pnl:+.0f}({pnl_pct:+.1f}%)")
        else:
            total_mv += cost * qty
    
    cash = real_acc.get('cash', 0)
    total = cash + total_mv
    init = real_acc.get('initial_capital', 25000)
    lines.append(f"  📊 总资产¥{total:,.0f} | 现金¥{cash:,.0f} | 仓位{total_mv/total*100:.0f}% | 总收益{(total-init)/init*100:+.2f}%")
    
    # 操作建议
    lines.append("")
    lines.append("  📝 实盘操作:")
    for p in real_pos:
        code = p['code']
        cost = p['avg_cost']
        qty = p['quantity']
        if code not in rt_prices:
            continue
        price = rt_prices[code]['price']
        pnl_pct = (price - cost) / cost * 100
        pct_today = rt_prices[code]['pct']
        stop_8 = cost * 0.92
        
        if price <= stop_8:
            lines.append(f"  🚨 {p['name']}: 触止损¥{stop_8:.2f}！建议立即卖出")
            lines.append(f"     ↳ 💡 原因: 机械止损线=成本¥{cost:.3f}×0.92（不超 8% 亏损），现价{price:.3f}跳下")
        elif pnl_pct >= 25:
            lines.append(f"  🎯 {p['name']}: 盈利{pnl_pct:+.1f}%达止盈②，建议清仓")
            lines.append(f"     ↳ 💡 原因: 盈利超 25%，锁定全部利润")
        elif pnl_pct >= 15:
            lines.append(f"  🎯 {p['name']}: 盈利{pnl_pct:+.1f}%达止盈①，建议减半仓({qty//2}股)")
            lines.append(f"     ↳ 💡 原因: 盈利达 15%首止盈位，减仓锁一半利润")
        elif pnl_pct > 8:
            lines.append(f"  📈 {p['name']}: 盈利{pnl_pct:+.1f}%，上移止损至成本价")
            lines.append(f"     ↳ 💡 原因: 盈利超 8%，改拉高止损不再赔成本")
        elif pnl_pct < -5:
            lines.append(f"  ⚠️ {p['name']}: 亏{pnl_pct:.1f}%，关注止损¥{stop_8:.2f}")
            lines.append(f"     ↳ 💡 原因: 距 8% 机械止损线({cost:.3f}×0.92={stop_8:.2f})还 {(price-stop_8)/stop_8*100:+.1f}%，跳下需减仓")
        elif phase == 'closing' and abs(pct_today) > 3:
            if pct_today > 3:
                lines.append(f"  ⚡ {p['name']}: 尾盘拉升{pct_today:+.1f}%，可减仓1/3锁利润")
            else:
                lines.append(f"  ⚡ {p['name']}: 尾盘跳水{pct_today:+.1f}%，不恐慌，观察明日")
        else:
            lines.append(f"  ✅ {p['name']}: 正常持有 ({pnl_pct:+.1f}%)")
    
    if cash > 5000 and total_mv / total < 0.5:
        lines.append(f"  💰 仓位偏低({total_mv/total*100:.0f}%)，可关注买入信号加仓")
    
    return '\n'.join(lines)

# ====================================================================
#  各阶段
# ====================================================================
def gen_pre_market(sim_positions, rules, cfg, auto_cfg):
    today = date.today().strftime('%m/%d')
    lines = [f"☀️ 盘前操作建议 ({today})", "=" * 40]
    
    # 获取所有相关股票行情
    all_codes = list(set(
        [p['stock_code'] for p in sim_positions] +
        [r['code'] for r in rules] +
        [p['code'] for p in load_real_positions()[1]]
    ))
    rt = get_sina_prices(all_codes)
    
    # 实盘（放最前面）
    lines.append(gen_real_section(rt, 'pre'))
    
    # 模拟盘概览
    acc = get_account()
    total_mv = sum(p['quantity'] * p.get('avg_cost', 0) for p in sim_positions)
    lines.append(f"\n🧪 模拟盘: 现金¥{acc.get('cash', 0):,.0f} | {len(sim_positions)}只 | 仓位{total_mv/(acc.get('cash',0)+total_mv)*100:.0f}%")
    for p in sim_positions:
        code = p['stock_code']
        if code in rt:
            pnl_pct = (rt[code]['price'] - p['avg_cost']) / p['avg_cost'] * 100
            emoji = "🟢" if pnl_pct >= 0 else "🔴"
            lines.append(f"  {emoji} {code} {p.get('stock_name',''):6s} {p['quantity']}股 @{p['avg_cost']:.2f} 浮盈{pnl_pct:+.1f}%")
    
    # 今日关键买入价位
    lines.append("\n🎯 今日关键价位:")
    buy_rules = [r for r in rules if 'buy' in r['level']]
    shown = set()
    for r in sorted(buy_rules, key=lambda x: x['trigger']):
        if r['code'] in shown:
            continue
        shown.add(r['code'])
        lines.append(f"  • {r['code']} {r['name']:6s} 触发¥{r['trigger']:.2f} ({r['level']})")
    
    # 止损价位
    lines.append("\n🚨 止损线:")
    for p in sim_positions:
        stop = p['avg_cost'] * 0.92
        lines.append(f"  • {p['stock_code']} {p.get('stock_name',''):6s} 止损¥{stop:.2f}")
    
    lines.append("\n📝 策略: 竞价观察→开盘5分钟不动→触发则按计划执行→14点后不开新仓")
    return '\n'.join(lines)


def gen_auction(sim_positions, rules):
    lines = ["🔔 竞价建议 (9:15-9:25)", "=" * 40]
    
    all_codes = list(set(
        [p['stock_code'] for p in sim_positions] +
        [r['code'] for r in rules] +
        [p['code'] for p in load_real_positions()[1]]
    ))
    rt = get_sina_prices(all_codes)
    
    # 实盘
    lines.append(gen_real_section(rt, 'auction'))
    
    # 模拟盘竞价
    lines.append("\n🧪 模拟盘竞价:")
    for p in sim_positions:
        code = p['stock_code']
        if code in rt:
            pct = rt[code]['pct']
            emoji = "🟢" if pct > 0 else "🔴" if pct < 0 else "⚪"
            lines.append(f"  {emoji} {code} {rt[code]['name']:6s} 竞价¥{rt[code]['price']:.2f} ({pct:+.1f}%)")
    
    # 触发监测
    lines.append("\n🎯 触发监测:")
    triggered = []
    close_to = []
    for r in rules:
        if 'buy' not in r['level']:
            continue
        code = r['code']
        if code in rt:
            price = rt[code]['price']
            if price <= r['trigger']:
                triggered.append((code, r['name'], price, r['trigger'], r['level']))
            elif price <= r['trigger'] * 1.02:
                close_to.append((code, r['name'], price, r['trigger'], r['level']))
    
    if triggered:
        for code, name, price, trigger, level in triggered:
            lines.append(f"  🔥 {code} {name} ¥{price:.2f} ≤ ¥{trigger:.2f} ({level}) → 开盘确认后建仓")
    if close_to:
        for code, name, price, trigger, level in close_to:
            gap = (price - trigger) / trigger * 100
            lines.append(f"  📍 {code} {name} ¥{price:.2f} (距触发{gap:.1f}%) → 密切关注")
    if not triggered and not close_to:
        lines.append("  ✅ 暂无接近触发的观察股")
    
    lines.append("\n📝 竞价操作: 9:15-9:20可撤单观察 | 9:20后不可撤 | 大幅低开>3%不急卖")
    return '\n'.join(lines)


def gen_intraday(sim_positions, rules):
    lines = ["📊 盘中操作建议", "=" * 40]
    
    all_codes = list(set(
        [p['stock_code'] for p in sim_positions] +
        [r['code'] for r in rules] +
        [p['code'] for p in load_real_positions()[1]]
    ))
    rt = get_sina_prices(all_codes)
    
    # 实盘
    lines.append(gen_real_section(rt, 'intraday'))
    
    # 模拟盘信号 — 每条附带 原因 + 数据依据
    acc = get_account()
    sim_total = sum(p['quantity'] * p.get('current_price', p.get('avg_cost', 0)) for p in sim_positions) + acc.get('cash', 0)
    lines.append(f"\n🧪 模拟盘信号（live_mirror 组合视角 · 总资¥{sim_total:,.0f} · 现金¥{acc.get('cash',0):,.0f}）:")
    action_count = 0
    
    # 按 code 分组 rules，方便查同一只股的所有阈值
    rules_by_code = {}
    for r in rules:
        rules_by_code.setdefault(r['code'], []).append(r)
    
    # === 持仓股的止损 / 止盈 信号 ===
    for p in sim_positions:
        code = p['stock_code']
        cost = p['avg_cost']
        if code not in rt:
            continue
        d = rt[code]
        price = d['price']
        pnl_pct = (price - cost) / cost * 100
        stop = cost * 0.92  # 8% 机械止损
        ctx = get_stock_context(code, rules_by_code.get(code, []), price)
        
        if price <= stop:
            # 止损 — 附带原因
            extra = []
            if ctx['ma20']:
                ma20_gap = (price - ctx['ma20']) / ctx['ma20'] * 100
                if ma20_gap < 0:
                    extra.append(f"距 MA20({ctx['ma20']:.2f}) 还跟 {ma20_gap:.1f}%")
            if ctx['trend_break'] and price <= ctx['trend_break']:
                extra.append(f"同时破 trend_break({ctx['trend_break']:.2f}) ⚠️趋势失效")
            extra_str = " | ".join(extra) if extra else ""
            lines.append(
                f"  🚨 止损 {code} {d['name']} ¥{price:.2f} ≤ 止损线¥{stop:.2f}(成本×0.92) | 浮亏{pnl_pct:+.1f}% 今日{d['pct']:+.1f}%"
            )
            if extra_str:
                lines.append(f"     ↳ {extra_str}")
            lines.append(f"     ↳ 💡 原因: 机械止损线=成本×0.92（不超 8% 亏损），现价已跳下。建议减半仓 {p['quantity']//2} 股")
            action_count += 1
        elif pnl_pct >= 15:
            lines.append(
                f"  🎯 止盈 {code} {d['name']} ¥{price:.2f} 浮盈{pnl_pct:+.1f}% 今日{d['pct']:+.1f}%"
            )
            lines.append(f"     ↳ 💡 原因: 浮盈达 15%，减半仓 {p['quantity']//2} 股锁利")
            action_count += 1
    
    # === 买入信号 — 附带原因 ===
    # 同一只股多个 buy 规则只取优先级最高的（buy_strong > buy_zone），避免刷屏
    triggered_buys = {}  # code -> best rule
    for r in rules:
        if 'buy' not in r['level']:
            continue
        if r.get('auto_buy_disabled'):
            continue
        code = r['code']
        if code not in rt:
            continue
        if rt[code]['price'] > r['trigger']:
            continue
        priority = {'buy_strong': 2, 'buy_zone': 1}.get(r['level'], 0)
        if code not in triggered_buys or priority > triggered_buys[code][0]:
            triggered_buys[code] = (priority, r)
    
    for code, (_, r) in triggered_buys.items():
        d = rt[code]
        held = any(p['stock_code'] == code for p in sim_positions)
        ctx = get_stock_context(code, rules_by_code.get(code, []), d['price'])
        
        warn = []
        if ctx['trend_break'] and d['price'] <= ctx['trend_break']:
            warn.append(f"⚠️ 同时破 trend_break({ctx['trend_break']:.2f})—折价别接")
        if d['pct'] < -3:
            warn.append(f"⚠️ 今日跌幅{d['pct']:+.1f}% 偏深")
        if held:
            warn.append("📍 已有持仓（不加仓）")
        
        if r['level'] == 'buy_zone':
            level_meaning = "MA10 附近 → 试探建仓"
        elif r['level'] == 'buy_strong':
            level_meaning = "MA20 优质建仓区"
        else:
            level_meaning = r['level']
        
        emoji = "⚠️" if (warn and not held) else ("📍" if held else "💰")
        lines.append(
            f"  {emoji} {code} {r['name']} ¥{d['price']:.2f} ≤ ¥{r['trigger']:.2f} ({r['level']}) 今日{d['pct']:+.1f}%"
        )
        lines.append(f"     ↳ 💡 含义: {level_meaning}")
        if r.get('source'):
            lines.append(f"     ↳ 🔖 来源: {r['source']}")
        if warn:
            lines.append(f"     ↳ {' | '.join(warn)}")
        action_count += 1
    
    if action_count == 0:
        lines.append("  ✅ 暂无操作信号")
    
    return '\n'.join(lines)


def gen_closing(sim_positions, rules):
    lines = ["🌅 尾盘建议 (14:00-15:00)", "=" * 40]
    
    all_codes = list(set(
        [p['stock_code'] for p in sim_positions] +
        [p['code'] for p in load_real_positions()[1]]
    ))
    rt = get_sina_prices(all_codes)
    
    # 实盘（放最前面，尾盘建议最重要）
    lines.append(gen_real_section(rt, 'closing'))
    
    # 模拟盘
    lines.append("\n🧪 模拟盘:")
    for p in sim_positions:
        code = p['stock_code']
        if code in rt:
            d = rt[code]
            pnl_pct = (d['price'] - p['avg_cost']) / p['avg_cost'] * 100
            amp = (d['high'] - d['low']) / d['yclose'] * 100 if d['yclose'] > 0 else 0
            emoji = "🟢" if d['pct'] > 0 else "🔴"
            lines.append(f"  {emoji} {code} {d['name']:6s} ¥{d['price']:.2f} 今日{d['pct']:+.1f}% 浮盈{pnl_pct:+.1f}%")
    
    lines.append("\n📝 尾盘原则: 不开新仓 | 拉升>3%可减仓 | 跳水>3%不恐慌卖 | 关注14:57集合竞价")
    return '\n'.join(lines)


def gen_review(sim_positions, rules):
    lines = ["📝 盘后复盘", "=" * 40]
    
    all_codes = list(set(
        [p['stock_code'] for p in sim_positions] +
        [p['code'] for p in load_real_positions()[1]]
    ))
    rt = get_sina_prices(all_codes)
    
    # 实盘
    lines.append(gen_real_section(rt, 'review'))
    
    # 模拟盘日盈亏
    total_pnl_today = 0
    lines.append("\n🧪 模拟盘今日:")
    for p in sim_positions:
        code = p['stock_code']
        if code in rt:
            d = rt[code]
            day_pnl = (d['price'] - d['yclose']) * p['quantity']
            total_pnl_today += day_pnl
            emoji = "🟢" if d['pct'] > 0 else "🔴"
            lines.append(f"  {emoji} {code} {d['name']:6s} {d['pct']:+.1f}% 日盈亏{day_pnl:+.0f}")
    lines.append(f"  💰 模拟盘今日: ¥{total_pnl_today:+,.0f}")
    
    # 近期交易
    trades = get_recent_trades(3)
    if trades:
        lines.append("\n📋 近3日交易:")
        for t in trades[:8]:
            dir_str = "买" if t['direction'] == 'BUY' else "卖"
            time_str = t.get('trade_time', '') or ''
            lines.append(f"  {t['trade_date']} {time_str} {dir_str} {t['stock_code']} {t.get('stock_name', '')} {t['quantity']}股 @{t['price']:.2f}")
    
    lines.append("\n📅 明日: 8:25阈值校准 → 8:30盘前建议 → 9:15竞价建议")
    return '\n'.join(lines)

# ====================================================================
#  主入口
# ====================================================================
def determine_phase():
    now = datetime.now()
    t = now.time()
    if now.weekday() >= 5:
        return 'review'
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
    sim_positions = get_sim_positions()
    rules = parse_alert_rules(cfg)
    
    generators = {
        'pre': lambda: gen_pre_market(sim_positions, rules, cfg, auto_cfg),
        'auction': lambda: gen_auction(sim_positions, rules),
        'intraday': lambda: gen_intraday(sim_positions, rules),
        'closing': lambda: gen_closing(sim_positions, rules),
        'review': lambda: gen_review(sim_positions, rules),
    }
    
    content = generators[phase]()
    print(content)
    
    # 保存推送历史
    save_push_history(phase, content)
    
    if not args.no_webhook:
        if push_webhook(content):
            logger.info("✓ 已推送企微")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
