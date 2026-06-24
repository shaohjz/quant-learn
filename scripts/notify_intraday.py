#!/usr/bin/env python
"""
scripts/notify_intraday.py — 盘中盯盘（盘中每 30 分钟运行）

设计理念：
  - 不罗列所有持仓的完整信息，只突出"该关注的"
  - 按涨跌幅排序，一眼看到谁在涨、谁在跌
  - 异常才标红/绿，正常的不啰嗦
  - 阈值触发单独突出，带 actionable 建议
  - 整体控制在 15 行以内，3 秒能看完

行情获取优先级：
  1. 腾讯财经 HTTP（不封IP，优先）
  2. 本地缓存文件 data/realtime_cache.json（由 AI 定时写入）
  3. 新浪财经 HTTP（兜底）

用法：
  python scripts/notify_intraday.py              # 正常推送
  python scripts/notify_intraday.py --dry-run     # 只打印，不推送
  python scripts/notify_intraday.py --force       # 强制运行
"""
import os
import sys
import json
import logging
import argparse
import sqlite3
from pathlib import Path
from datetime import datetime, date, time as dtime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

os.environ.setdefault("QUANT_DB_PATH", str(ROOT / "data" / "sim_live_mirror.db"))

from wecom_webhook import push_markdown, get_webhook_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ====================================================================
#  行情获取（多源降级）
# ====================================================================
def get_prices(codes):
    """获取实时行情，多源降级"""
    if not codes:
        return {}

    # 1. 腾讯财经（不封IP，http 非 https）
    try:
        result = _get_tencent_prices(codes)
        if result:
            return result
    except Exception as e:
        logger.warning(f"腾讯行情失败: {e}")

    # 2. 本地缓存（由 AI 定时写入）
    try:
        cache_path = ROOT / "data" / "realtime_cache.json"
        if cache_path.exists():
            with open(cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            # 检查缓存是否在 5 分钟内
            cache_time = cache.get("timestamp", 0)
            if isinstance(cache_time, str):
                cache_time = datetime.fromisoformat(cache_time).timestamp()
            if time() - cache_time < 300:  # 5 分钟内
                result = {k: v for k, v in cache.get("prices", {}).items() if k in codes}
                if result:
                    logger.info(f"使用本地缓存行情 ({len(result)} 只)")
                    return result
    except Exception as e:
        logger.warning(f"本地缓存读取失败: {e}")

    # 3. 新浪兜底
    try:
        result = _get_sina_prices(codes)
        if result:
            return result
    except Exception as e:
        logger.warning(f"新浪行情失败: {e}")

    return {}


def _get_tencent_prices(codes):
    """腾讯财经行情接口（http，不封IP）"""
    import re as _re
    import urllib.request
    tencent_codes = []
    for c in codes:
        prefix = 'sh' if c.startswith(('60', '68', '11', '5')) else 'sz'
        tencent_codes.append(prefix + c)
    url = 'http://qt.gtimg.cn/q=' + ','.join(tencent_codes)
    try:
        r = urllib.request.urlopen(url, timeout=8)
        text = r.read().decode('gbk')
    except Exception as e:
        raise e
    prices = {}
    for line in text.strip().split('\n'):
        if not line.strip():
            continue
        m = _re.search(r'(s[hz]\d+)="(.+?)"', line)
        if m:
            parts = m.group(2).split('~')
            if len(parts) >= 40:
                code = parts[2]
                name = parts[1]
                try:
                    price = float(parts[3]) if parts[3] else 0
                    yclose = float(parts[4]) if parts[4] else 0
                    pct = round((price - yclose) / yclose * 100, 2) if yclose > 0 else 0.0
                    prices[code] = {
                        'name': name, 'price': price,
                        'yclose': yclose, 'high': float(parts[33]) if parts[33] else 0,
                        'low': float(parts[34]) if parts[34] else 0,
                        'volume': float(parts[6]) if parts[6] else 0,
                        'amount': float(parts[37]) if parts[37] else 0, 'pct': pct,
                    }
                except (ValueError, IndexError):
                    continue
    return prices


def _get_sina_prices(codes):
    """新浪财经行情接口（https 兜底）"""
    import re as _re
    import urllib.request
    import ssl
    sina_codes = []
    for c in codes:
        prefix = 'sh' if c.startswith(('60', '68', '11', '5')) else 'sz'
        sina_codes.append(prefix + c)
    url = 'https://hq.sinajs.cn/list=' + ','.join(sina_codes)
    headers = {'Referer': 'https://finance.sina.com.cn'}
    ctx = ssl._create_unverified_context()
    r = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=8, context=ctx)
    text = r.read().decode('gbk')
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
                        'name': parts[0], 'price': current_price,
                        'yclose': yclose, 'high': float(parts[4]) if parts[4] else 0,
                        'low': float(parts[5]) if parts[5] else 0,
                        'volume': float(parts[8]) if parts[8] else 0,
                        'amount': float(parts[9]) if parts[9] else 0, 'pct': pct,
                    }
                except (ValueError, IndexError):
                    continue
    return prices


# ====================================================================
#  数据源
# ====================================================================
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


def load_real_alert_rules():
    """从 config.yaml 的 real_portfolio_rules 加载实盘阈值规则"""
    import yaml
    cfg_path = ROOT / "config.yaml"
    if not cfg_path.exists():
        return []
    cfg = yaml.safe_load(cfg_path.read_text(encoding='utf-8')) or {}
    rules = cfg.get('real_portfolio_rules', {})
    flattened = []
    for code, info in rules.items():
        name = info.get('name', code)
        for rule_name, rule_cfg in info.get('rules', {}).items():
            flattened.append({
                'code': code,
                'name': name,
                'rule': rule_name,
                'trigger': rule_cfg['trigger'],
                'dir': rule_cfg['dir'],
                'message': rule_cfg['msg'],
            })
    return flattened


def in_trade_hours(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (dtime(9, 30) <= t <= dtime(11, 30)) or (dtime(13, 0) <= t <= dtime(15, 0))


# ====================================================================
#  消息生成 — 紧凑版
# ====================================================================
def generate_intraday_watch(now: datetime) -> str:
    """生成紧凑版盘中盯盘 Markdown"""
    time_str = now.strftime("%H:%M")

    lines = []
    lines.append(f"**👁️ 盘中 {time_str}**")
    lines.append("")

    # --- 大盘指数 ---
    idx_codes = ['000001', '399001', '399006', '000688']
    idx_names = {'000001': '上证', '399001': '深证', '399006': '创业板', '000688': '科创50'}
    idx_rt = get_prices(idx_codes)
    if idx_rt:
        idx_parts = []
        for code, name in idx_names.items():
            d = idx_rt.get(code)
            if d:
                emoji = "🟢" if d['pct'] >= 0 else "🔴"
                idx_parts.append(f"{emoji}{name}{d['pct']:+.2f}%")
        if idx_parts:
            lines.append(' '.join(idx_parts))
            lines.append("")

    # 收集所有持仓
    all_items = []

    # 实盘持仓
    real_acc, real_pos = load_real_positions()
    if real_pos:
        real_codes = [p['code'] for p in real_pos]
        rt = get_prices(real_codes)
        for p in real_pos:
            code = p['code']
            d = rt.get(code, {})
            price = d.get('price', 0)
            pct = d.get('pct', 0)
            cost = p.get('avg_cost', 0)
            qty = p.get('quantity', 0)
            pnl = (price - cost) * qty if price and cost else 0
            pnl_pct = (price - cost) / cost * 100 if cost > 0 else 0
            all_items.append({
                'name': d.get('name', p.get('name', '')),
                'code': code, 'price': price, 'pct': pct,
                'pnl': pnl, 'pnl_pct': pnl_pct,
                'qty': qty, 'cost': cost,
                'source': '实盘',
            })

    # 模拟盘持仓
    sim_pos = load_sim_positions()
    if sim_pos:
        sim_codes = [p['stock_code'] for p in sim_pos]
        rt = get_prices(sim_codes)
        for p in sim_pos:
            code = p['stock_code']
            d = rt.get(code, {})
            price = d.get('price', p['current_price'])
            pct = d.get('pct', 0)
            pnl = (price - p['avg_cost']) * p['quantity']
            pnl_pct = (price - p['avg_cost']) / p['avg_cost'] * 100
            all_items.append({
                'name': p['stock_name'], 'code': code, 'price': price, 'pct': pct,
                'pnl': pnl, 'pnl_pct': pnl_pct,
                'qty': p['quantity'], 'cost': p['avg_cost'],
                'source': '模拟',
            })

    # 阈值监控标的
    rules = load_real_alert_rules()
    watch_codes = list({r['code'] for r in rules})

    # 合并所有需要查询的代码
    all_codes = list(set(
        idx_codes +
        [p['code'] for p in real_pos] +
        [p['stock_code'] for p in sim_pos] +
        watch_codes
    ))

    # 批量获取行情
    rt_all = get_prices(all_codes)

    # 检查阈值触发
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

    # --- 阈值触发（最优先） ---
    if triggered:
        lines.append("**🔔 触发**")
        for r in triggered:
            d = rt_all.get(r['code'], {})
            pct = d.get('pct', 0)
            arrow = "↓" if r['dir'] == 'below' else "↑"
            lines.append(f"**{r['name']}** ¥{d['price']:.2f}({pct:+.2f}%) {arrow}¥{r['trigger']:.2f}")
            lines.append(f"> {r['message']}")
        lines.append("")

    # --- 持仓涨跌排行 ---
    if all_items:
        # 只显示该关注的：涨跌幅 > 2% 或浮亏 > 5%
        notable = [x for x in all_items if abs(x['pct']) >= 2 or x['pnl_pct'] <= -5]

        if notable:
            lines.append("**📊 关注**")
            for item in sorted(notable, key=lambda x: x['pct']):
                emoji = "🟢" if item['pnl'] >= 0 else "🔴"
                tag = f"[{item['source']}]"
                lines.append(
                    f"{emoji} {tag}**{item['name']}** ¥{item['price']:.2f}({item['pct']:+.2f}%) "
                    f"浮盈{item['pnl']:+.0f}({item['pnl_pct']:+.1f}%)"
                )
            lines.append("")

        # 快速概览
        overview_parts = []
        for item in sorted(all_items, key=lambda x: x['pct']):
            emoji = "🟢" if item['pnl'] >= 0 else "🔴"
            overview_parts.append(f"{emoji}{item['name']}{item['pct']:+.1f}%")
        lines.append(f"**📋** {' | '.join(overview_parts)}")
        lines.append("")
    else:
        lines.append("**📋** 当前无持仓")
        lines.append("")

    lines.append("---")
    lines.append(f"_⏰ {time_str}_")
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
            logger.warning("⚠️ 推送失败")
            print(content)

    logger.info("=== 盘中盯盘 完成 ===")
    return 0


if __name__ == "__main__":
    # 修复 time() 导入
    from time import time
    sys.exit(main())
