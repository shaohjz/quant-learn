#!/usr/bin/env python
"""
scripts/notify_scan_result.py — 每日扫描结果企微推送

功能：
  1. 盘前(09:35)：推送早盘扫描结果（观察列表、交易信号、数据源状态）
  2. 尾盘(14:30)：推送尾盘扫描结果（当日交易情况、持仓变化）
  3. 从 DB / 文件系统读取扫描结果，汇总后推送企微
  4. 支持 --phase morning|closing|auto 参数

使用：
  python scripts/notify_scan_result.py [--phase morning|closing|auto] [--no-webhook] [--dry-run]
  --phase auto: 根据当前时间自动判断（09:00-12:00=morning, 12:00-15:30=closing）
  --dry-run: 只打印不推送
"""
import sys
import json
import logging
import argparse
import urllib.request
import sqlite3
from pathlib import Path
from datetime import datetime, date, time as dtime, timedelta
import re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = ROOT / "data" / "sim_live_mirror.db"
OUTPUT_DIR = ROOT / "output"
DAILY_REPORTS_DIR = OUTPUT_DIR / "daily-reports"
INTRADAY_SCAN_DIR = OUTPUT_DIR / "intraday_scans"
REVIEW_DIR = OUTPUT_DIR / "reviews"

# ====================================================================
#  配置加载
# ====================================================================
def load_webhook() -> str:
    """优先读 config.local.yaml，回退到 config.yaml"""
    local_cfg_path = ROOT / "config.local.yaml"
    if local_cfg_path.exists():
        import yaml
        d = yaml.safe_load(local_cfg_path.read_text(encoding='utf-8')) or {}
        url = (d.get("notifier") or {}).get("wecom_webhook", "")
        if url:
            return url
    # 回退 config.yaml
    cfg_path = ROOT / "config.yaml"
    if cfg_path.exists():
        import yaml
        d = yaml.safe_load(cfg_path.read_text(encoding='utf-8')) or {}
        return (d.get("notify") or {}).get("wecom_webhook", "")
    return ""

def push_wecom(content: str, msgtype: str = "text") -> bool:
    """推送消息到企微机器人"""
    url = load_webhook()
    if not url:
        logger.warning("未配置企微 Webhook，仅打印不发送")
        print(f"[DRY] 企微推送内容:\n{content}")
        return False
    if msgtype == "markdown":
        payload = json.dumps({
            "msgtype": "markdown",
            "markdown": {"content": content}
        }, ensure_ascii=False).encode('utf-8')
    else:
        payload = json.dumps({
            "msgtype": "text",
            "text": {"content": content}
        }, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        if result.get("errcode", 0) != 0:
            logger.error(f"企微返回错误: {result}")
            return False
        logger.info("✓ 企微推送成功")
        return True
    except Exception as e:
        logger.error(f"推送失败: {e}")
        return False


# ====================================================================
#  数据获取
# ====================================================================
def get_sina_prices(codes: list) -> dict:
    """从新浪财经获取实时行情"""
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
    except Exception as e:
        logger.warning(f"获取行情失败: {e}")
        return {}
    prices = {}
    for line in text.strip().split('\n'):
        m = re.search(r'hq_str_(s[hz])(\d+)="(.+?)"', line)
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
                        'yclose': yclose,
                        'pct': pct,
                    }
                except ValueError:
                    continue
    return prices


def get_watchlist_codes() -> list:
    """从 config.yaml 读取观察列表股票代码"""
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding='utf-8')) or {}
        watchlist = cfg.get('watchlist', {})
        codes = []
        # user_manual 观察列表
        user_manual = watchlist.get('user_manual', {}) or {}
        for code, info in user_manual.items():
            if info.get('enabled', True):
                codes.append(code)
        # auto_discovered 观察列表
        auto_disc = watchlist.get('auto_discovered', {}) or {}
        for code in auto_disc.keys():
            if code not in codes:
                codes.append(code)
        return codes
    except Exception as e:
        logger.warning(f"读取观察列表失败: {e}")
        return []


def get_sim_positions() -> list:
    """获取模拟账户持仓（统一字段名: code, name）"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM sim_positions WHERE account_id=1 AND quantity > 0"
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            # 统一字段名：stock_code → code, stock_name → name
            d['code'] = d.get('stock_code', d.get('code', ''))
            d['name'] = d.get('stock_name', d.get('name', ''))
            result.append(d)
        return result
    except Exception as e:
        logger.warning(f"读取模拟持仓失败: {e}")
        return []


def get_real_positions() -> list:
    """获取实盘持仓（从 config_real.yaml）"""
    try:
        import yaml
        path = ROOT / "config_real.yaml"
        if not path.exists():
            return []
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        return data.get('positions', [])
    except Exception as e:
        logger.warning(f"读取实盘持仓失败: {e}")
        return []


def get_recent_trades(days: int = 1) -> list:
    """获取近期交易记录"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        since = (date.today() - timedelta(days=days)).isoformat()
        rows = conn.execute(
            "SELECT * FROM sim_trades WHERE account_id=1 AND trade_date >= ? ORDER BY created_at DESC",
            (since,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"读取交易记录失败: {e}")
        return []


def get_account() -> dict:
    """获取模拟账户信息"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM sim_account WHERE id=1").fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception as e:
        logger.warning(f"读取账户信息失败: {e}")
        return {}


def check_data_freshness() -> dict:
    """检查数据是否最新（数据最后更新日期）"""
    try:
        data_dir = ROOT / "data"
        latest = None
        for f in data_dir.glob("*.csv"):
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if latest is None or mtime > latest:
                latest = mtime
        if latest:
            age_hours = (datetime.now() - latest).total_seconds() / 3600
            return {"fresh": age_hours < 18, "age_hours": round(age_hours, 1), "last_update": latest.strftime("%m-%d %H:%M")}
        return {"fresh": False, "age_hours": 999, "last_update": "未知"}
    except Exception as e:
        logger.warning(f"检查数据新鲜度失败: {e}")
        return {"fresh": False, "age_hours": 999, "last_update": "未知"}


def get_latest_review() -> dict:
    """读取最新的复盘报告摘要"""
    try:
        today = date.today().isoformat()
        review_path = REVIEW_DIR / f"{today}.md"
        if not review_path.exists():
            # 尝试找最近的一份
            reviews = sorted(REVIEW_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
            if reviews:
                review_path = reviews[0]
            else:
                return {}
        content = review_path.read_text(encoding='utf-8')
        # 提取摘要信息
        summary = {"path": str(review_path), "has_content": True}
        # 查找关键数字
        for line in content.split('\n')[:50]:
            if '总资产' in line or 'total' in line.lower():
                summary['asset_line'] = line.strip()
            if '收益率' in line or 'return' in line.lower():
                summary['return_line'] = line.strip()
        return summary
    except Exception as e:
        logger.warning(f"读取复盘报告失败: {e}")
        return {}


# ====================================================================
#  消息生成
# ====================================================================
def gen_morning_content() -> str:
    """生成早盘扫描结果通知（09:35 推送）"""
    today = date.today().strftime("%Y-%m-%d")
    lines = []
    lines.append(f"📈 早盘扫描结果 | {today} 09:35")
    lines.append("=" * 36)

    # 1. 数据源状态
    data_status = check_data_freshness()
    if data_status["fresh"]:
        ds_emoji = "✅"
        ds_msg = f"数据正常（{data_status['last_update']} 更新）"
    else:
        ds_emoji = "⚠️"
        ds_msg = f"数据滞后 {data_status['age_hours']}h（最后: {data_status['last_update']}）"
    lines.append(f"\n📊 数据源: {ds_emoji} {ds_msg}")

    # 2. 观察列表
    watch_codes = get_watchlist_codes()
    lines.append(f"\n👀 观察列表（{len(watch_codes)} 只）")
    if watch_codes:
        # 取行情
        prices = get_sina_prices(watch_codes)
        shown = 0
        for code in watch_codes[:10]:  # 最多显示10只
            if code in prices:
                d = prices[code]
                emoji = "📈" if d['pct'] >= 0 else "📉"
                lines.append(f"  {emoji} {code} {d['name']} {d['price']:.3f} ({d['pct']:+.2f}%)")
                shown += 1
        if len(watch_codes) > 10:
            lines.append(f"  ... 还有 {len(watch_codes) - 10} 只")
    else:
        lines.append("  （观察列表为空）")

    # 3. 持仓概览
    sim_pos = get_sim_positions()
    real_pos = get_real_positions()
    lines.append(f"\n💼 持仓概览")
    lines.append(f"  模拟账户: {len(sim_pos)} 只持仓")
    lines.append(f"  实盘账户: {len(real_pos)} 只持仓")

    # 4. 账户状态
    acc = get_account()
    if acc:
        total = acc.get('total_value', 0)
        cash = acc.get('cash', 0)
        lines.append(f"\n💰 模拟账户")
        lines.append(f"  总资产 ¥{total:,.2f} | 现金 ¥{cash:,.2f}")

    # 5. 近期交易
    trades = get_recent_trades(days=1)
    if trades:
        lines.append(f"\n📝 昨日交易 ({len(trades)} 笔)")
        for t in trades[:5]:
            side = t.get('side', '')
            code = t.get('code', '')
            qty = t.get('quantity', 0)
            price = t.get('price', 0)
            lines.append(f"  {side} {code} {qty}股 @¥{price:.3f}")
    else:
        lines.append("\n📝 昨日交易: 无")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("回复可查看详情 / 开始盯盘")

    return '\n'.join(lines)


def gen_closing_content() -> str:
    """生成尾盘扫描结果通知（14:30 推送）"""
    today = date.today().strftime("%Y-%m-%d")
    lines = []
    lines.append(f"📉 尾盘扫描结果 | {today} 14:30")
    lines.append("=" * 36)

    # 1. 今日交易情况
    trades = get_recent_trades(days=1)
    lines.append(f"\n📝 今日交易 ({len(trades)} 笔)")
    if trades:
        buy_count = sum(1 for t in trades if t.get('side', '').lower() == 'buy')
        sell_count = sum(1 for t in trades if t.get('side', '').lower() == 'sell')
        lines.append(f"  买入 {buy_count} 笔 | 卖出 {sell_count} 笔")
        for t in trades[:5]:
            side = t.get('side', '')
            code = t.get('code', '')
            name = t.get('name', code)
            qty = t.get('quantity', 0)
            price = t.get('price', 0)
            emoji = "🟢" if side.lower() == 'buy' else "🔴"
            lines.append(f"  {emoji} {side} {code} {name} {qty}股 @¥{price:.3f}")
        if len(trades) > 5:
            lines.append(f"  ... 还有 {len(trades) - 5} 笔")
    else:
        lines.append("  今日无交易")

    # 2. 持仓实时行情
    sim_pos = get_sim_positions()
    real_pos = get_real_positions()
    all_codes = [p['code'] for p in sim_pos]
    # real_pos 结构不同（来自 config_real.yaml），字段为 code
    for p in real_pos:
        c = p.get('code', '')
        if c:
            all_codes.append(c)
    prices = get_sina_prices(all_codes) if all_codes else {}

    if sim_pos:
        lines.append(f"\n💼 模拟持仓 ({len(sim_pos)} 只)")
        total_mv = 0
        for p in sim_pos[:5]:
            code = p['code']
            qty = p['quantity']
            cost = p.get('avg_cost', 0)
            if code in prices:
                price = prices[code]['price']
                pct = prices[code]['pct']
                pnl = (price - cost) * qty if cost else 0
                emoji = "📈" if pct >= 0 else "📉"
                lines.append(f"  {emoji} {code} {prices[code]['name']} {price:.3f}({pct:+.2f}%) 浮盈{pnl:+.0f}")
                total_mv += price * qty
        if len(sim_pos) > 5:
            lines.append(f"  ... 还有 {len(sim_pos) - 5} 只")

    # 3. 账户状态
    acc = get_account()
    if acc:
        total = acc.get('total_value', 0)
        cash = acc.get('cash', 0)
        lines.append(f"\n💰 模拟账户")
        lines.append(f"  总资产 ¥{total:,.2f} | 现金 ¥{cash:,.2f}")

    # 4. 复盘报告状态
    review = get_latest_review()
    if review.get('has_content'):
        lines.append(f"\n📊 复盘报告: ✅ 已生成")
    else:
        lines.append(f"\n📊 复盘报告: ⏳ 待生成（15:05后）")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("收盘后自动生成复盘报告")

    return '\n'.join(lines)


# ====================================================================
#  阶段判断
# ====================================================================
def determine_phase() -> str:
    """根据当前时间自动判断阶段"""
    now = datetime.now()
    t = now.time()
    if t < dtime(12, 0):
        return 'morning'
    else:
        return 'closing'


# ====================================================================
#  主入口
# ====================================================================
def main():
    parser = argparse.ArgumentParser(description='每日扫描结果企微推送')
    parser.add_argument('--phase', choices=['morning', 'closing', 'auto'], default='auto',
                        help='推送阶段: morning(09:35) / closing(14:30) / auto')
    parser.add_argument('--no-webhook', action='store_true', help='不推送，只打印')
    parser.add_argument('--dry-run', action='store_true', help='同 --no-webhook')
    parser.add_argument('--msgtype', choices=['text', 'markdown'], default='text',
                        help='消息类型（企微 text 或 markdown，默认 text）')
    args = parser.parse_args()

    phase = args.phase if args.phase != 'auto' else determine_phase()
    logger.info(f"生成扫描推送: phase={phase}")

    if phase == 'morning':
        content = gen_morning_content()
    else:
        content = gen_closing_content()

    print(content)
    print()

    no_push = args.no_webhook or args.dry_run
    if no_push:
        logger.info("⚠️ --no-webhook/--dry-run 模式，不推送")
        return 0

    # 推送
    ok = push_wecom(content, msgtype=args.msgtype)
    if ok:
        logger.info(f"✓ {phase} 扫描结果已推送企微")
    else:
        logger.error(f"✗ {phase} 扫描结果推送失败")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
