#!/usr/bin/env python
"""
scripts/daily_review.py - 每日 9:00 收盘后复盘 + iwiki 写入

读取昨日 sim_trades + 当前持仓 + 行情快照，生成 markdown 复盘:
  1. 写入 iwiki 4018670685 下的子页（标题：YYYY年M月D日 市场分析（AI模拟版））
  2. 同时推送精炼版到企微群 webhook

用法:
  python scripts\daily_review.py [日期]
  默认: 昨日（如周一跑则取上周五）
"""
import os
import sys
import json
import logging
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, date, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QUANT_DB_PATH', str(ROOT / 'data' / 'sim_live_mirror.db'))

from sim.db import get_conn

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# 加载 webhook URL
WEBHOOK_URL = ""
try:
    import yaml
    cfg_path = ROOT / 'config.local.yaml'
    if cfg_path.exists():
        cfg = yaml.safe_load(cfg_path.read_text(encoding='utf-8'))
        WEBHOOK_URL = (cfg or {}).get('notifier', {}).get('wecom_webhook', '')
except Exception:
    pass

IWIKI_PARENT_ID = 4018670685
IWIKI_SPACE_ID = 328368432


def push_webhook(content: str) -> bool:
    if not WEBHOOK_URL:
        logger.warning("未配置 webhook URL")
        return False
    body = json.dumps({'msgtype': 'markdown', 'markdown': {'content': content}}).encode('utf-8')
    req = urllib.request.Request(WEBHOOK_URL, data=body, headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception as e:
        logger.error(f"webhook 推送失败: {e}")
        return False


def get_target_date():
    """如果是周末，回退到周五。如果指定参数则用参数。"""
    if len(sys.argv) > 1:
        return date.fromisoformat(sys.argv[1])
    today = date.today()
    # 默认复盘"昨天"，但要避开周末
    yesterday = today - timedelta(days=1)
    while yesterday.weekday() >= 5:  # 5=周六, 6=周日
        yesterday -= timedelta(days=1)
    return yesterday


def fetch_trades(target_date):
    """拉指定日期的虚拟成交"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM sim_trades WHERE trade_date=? AND broker='live_mirror' ORDER BY id",
        (target_date.isoformat(),)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_positions():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM sim_positions WHERE account_id=1 ORDER BY market_value DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_account():
    conn = get_conn()
    row = conn.execute("SELECT * FROM sim_account WHERE id=1").fetchone()
    conn.close()
    return dict(row) if row else None


def fetch_yesterday_nav(target_date):
    """获取昨日及前日净值"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM sim_daily_nav WHERE account_id=1 AND trade_date <= ? ORDER BY trade_date DESC LIMIT 5",
        (target_date.isoformat(),)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def write_daily_nav(target_date, account, positions):
    """写入当日净值"""
    market_value = sum(p['market_value'] for p in positions)
    total_value = market_value + account['cash']
    cumulative_return = (total_value / account['initial_cash'] - 1) * 100
    
    conn = get_conn()
    # 计算 daily_return
    last = conn.execute(
        "SELECT total_value FROM sim_daily_nav WHERE account_id=1 AND trade_date < ? ORDER BY trade_date DESC LIMIT 1",
        (target_date.isoformat(),)
    ).fetchone()
    prev_value = last['total_value'] if last else account['initial_cash']
    daily_return = (total_value / prev_value - 1) * 100 if prev_value > 0 else 0
    
    # 计算最大回撤
    all_navs = conn.execute(
        "SELECT total_value FROM sim_daily_nav WHERE account_id=1 ORDER BY trade_date"
    ).fetchall()
    peak = account['initial_cash']
    for r in all_navs:
        peak = max(peak, r['total_value'])
    peak = max(peak, total_value)
    max_drawdown = (total_value / peak - 1) * 100
    
    conn.execute(
        """INSERT OR REPLACE INTO sim_daily_nav 
           (account_id, trade_date, total_value, cash, market_value, daily_return, cumulative_return, max_drawdown)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?)""",
        (target_date.isoformat(), total_value, account['cash'], market_value, daily_return, cumulative_return, max_drawdown)
    )
    conn.close()
    return {'total_value': total_value, 'daily_return': daily_return, 'cumulative_return': cumulative_return, 'max_drawdown': max_drawdown}


def fetch_qmt_summary():
    """从 dispatch 日志里拼出 QMT 模拟账户当日交易与累计 PnL（如果能连 QMT 可另外拉实时账户状态）"""
    today = date.today().isoformat()
    log_path = ROOT / "output" / f"fusion_dispatch_{today}.json"
    summary = {"available": False, "qmt_decisions_total": 0,
               "qmt_executed": 0, "qmt_dropped": 0, "dry_run": True,
               "sample": []}
    if log_path.exists():
        try:
            log = json.loads(log_path.read_text(encoding="utf-8"))
            summary["available"] = True
            summary["qmt_decisions_total"] = (
                len(log.get("qmt_decisions", [])) + len(log.get("qmt_dropped", []))
            )
            summary["qmt_executed"] = len(log.get("qmt_decisions", []))
            summary["qmt_dropped"] = len(log.get("qmt_dropped", []))
            summary["dry_run"] = bool(log.get("qmt_dry_run", True))
            summary["sample"] = log.get("qmt_decisions", [])[:8]
            summary["advisor_decisions"] = log.get("advisor_decisions", [])
        except Exception as e:
            logger.warning(f"读 fusion_dispatch 日志失败: {e}")
    return summary


def fetch_advisor_hits(target_date):
    """读历史 dispatch 日志评估建议命中率：
       - 看 N 日前推送的 advisor 建议，在 target_date 是否走对了方向
       这里只做一个轻量实现：近 5 日 dispatch 记录里的 advisor_decisions 计数 + 列表。真正命中率需下一阶段充后续价才能算。
    """
    log_dir = ROOT / "output"
    advisors = []
    for delta in range(0, 5):
        d = (target_date - timedelta(days=delta)).isoformat()
        f = log_dir / f"fusion_dispatch_{d}.json"
        if f.exists():
            try:
                log = json.loads(f.read_text(encoding="utf-8"))
                for a in log.get("advisor_decisions", []):
                    advisors.append({"date": d, **a})
            except Exception:
                pass
    return advisors


def generate_markdown(target_date, account, positions, trades, nav_info, navs_history):
    """生成完整复盘 markdown"""
    md = []
    md.append(f"# {target_date.year}年{target_date.month}月{target_date.day}日 市场分析（AI模拟版）")
    md.append("")
    md.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 复盘日: {target_date.isoformat()}")
    md.append("")
    
    # ========== 账户总览 ==========
    md.append("## 📊 账户总览")
    md.append("")
    md.append("| 项目 | 数值 |")
    md.append("| --- | --- |")
    md.append(f"| 初始本金 | ¥{account['initial_cash']:,.2f} |")
    md.append(f"| 当日总资产 | ¥{nav_info['total_value']:,.2f} |")
    md.append(f"| 现金 | ¥{account['cash']:,.2f} |")
    md.append(f"| 持仓市值 | ¥{nav_info['total_value'] - account['cash']:,.2f} |")
    md.append(f"| 当日收益率 | {nav_info['daily_return']:+.2f}% |")
    md.append(f"| 累计收益率 | {nav_info['cumulative_return']:+.2f}% |")
    md.append(f"| 最大回撤 | {nav_info['max_drawdown']:+.2f}% |")
    md.append("")
    
    # ========== 持仓明细 ==========
    md.append("## 💼 当前持仓")
    md.append("")
    if positions:
        md.append("| 代码 | 名称 | 数量 | 成本 | 现价 | 市值 | 浮亏 | % |")
        md.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for p in positions:
            sign = "+" if p['pnl'] >= 0 else ""
            md.append(f"| {p['stock_code']} | {p['stock_name']} | {p['quantity']} | {p['avg_cost']:.3f} | {p['current_price']:.2f} | {p['market_value']:.2f} | {sign}{p['pnl']:.2f} | {p['pnl_pct']:+.2f}% |")
    else:
        md.append("_空仓_")
    md.append("")
    
    # ========== 当日虚拟交易 ==========
    md.append(f"## 🤖 {target_date.isoformat()} AI 虚拟交易")
    md.append("")
    if trades:
        md.append(f"**共 {len(trades)} 笔成交：**")
        md.append("")
        md.append("| 时间 | 方向 | 名称 | 数量 | 价格 | 金额 | 信号 |")
        md.append("| --- | --- | --- | --- | --- | --- | --- |")
        for t in trades:
            ts = t['created_at'].split(' ')[1][:5] if ' ' in t['created_at'] else ''
            dir_emoji = "🟢 BUY" if t['direction'] == 'BUY' else "🔴 SELL"
            md.append(f"| {ts} | {dir_emoji} | {t['stock_name']} | {t['quantity']} | {t['price']:.2f} | {t['amount']:.2f} | {t['signal_reason'][:30]} |")
    else:
        md.append("_当日无虚拟交易（无阈值触发）_")
    md.append("")
    
    # ========== 历史净值曲线 ==========
    if len(navs_history) >= 2:
        md.append("## 📈 近期净值")
        md.append("")
        md.append("| 日期 | 总资产 | 当日 | 累计 |")
        md.append("| --- | --- | --- | --- |")
        for n in navs_history[:5]:
            md.append(f"| {n['trade_date']} | ¥{n['total_value']:,.2f} | {n['daily_return']:+.2f}% | {n['cumulative_return']:+.2f}% |")
        md.append("")
    
    # ========== 一句话点评 ==========
    md.append("## 💡 一句话点评")
    md.append("")
    if nav_info['daily_return'] > 1:
        md.append(f"📈 当日收益 {nav_info['daily_return']:+.2f}%，跑赢整体市场（如有）。")
    elif nav_info['daily_return'] < -1:
        md.append(f"📉 当日下跌 {nav_info['daily_return']:.2f}%，关注是否有止损信号未触发。")
    else:
        md.append(f"➖ 当日波动 {nav_info['daily_return']:+.2f}%，无明显方向。")
    md.append("")

    # ========== ★ QMT 全策略账户 ==========
    qmt = fetch_qmt_summary()
    md.append("## 🤖 QMT 全策略账户（模拟 90072426）")
    md.append("")
    if not qmt["available"]:
        md.append("_今日未运行 run_fusion_dispatch 或未产生记录_")
    else:
        md.append(f"- 运行模式：{'**dry-run**（未真下单）' if qmt['dry_run'] else '**LIVE**（已下单到 QMT）'}")
        md.append(f"- 今日决策总数：{qmt['qmt_decisions_total']}【执行 {qmt['qmt_executed']}、超限丢弃 {qmt['qmt_dropped']}】")
        if qmt["sample"]:
            md.append("")
            md.append("| # | 动作 | 代码 | 数量 | 价格 | 置信度 | 规则 |")
            md.append("| --- | --- | --- | --- | --- | --- | --- |")
            for i, d in enumerate(qmt["sample"], 1):
                md.append(
                    f"| {i} | {d.get('action','')} | {d.get('stock_code','')} | "
                    f"{d.get('qty','')} | {d.get('price','')} | "
                    f"{d.get('confidence','')} | {d.get('rule','')} |"
                )
    md.append("")

    # ========== ★ AI 给真实账户的建议 ==========
    md.append("## 📝 AI 给真实账户的建议（仅推送不下单）")
    md.append("")
    advisor_today = (qmt.get("advisor_decisions") or []) if qmt.get("available") else []
    if not advisor_today:
        md.append("_今日无 AI 给真实账户的个股操作建议_")
    else:
        md.append("| 动作 | 代码 | 数量 | 价格 | 置信度 | 规则 | 说明 |")
        md.append("| --- | --- | --- | --- | --- | --- | --- |")
        for d in advisor_today:
            md.append(
                f"| {d.get('action','')} | {d.get('stock_code','')} | {d.get('qty','')} | "
                f"{d.get('price','')} | {d.get('confidence','')} | "
                f"{d.get('rule','')} | {(d.get('reason') or '')[:40]} |"
            )

    advisors_history = fetch_advisor_hits(target_date)
    if advisors_history:
        md.append("")
        md.append(f"近 5 日 advisor 建议总数：{len(advisors_history)} 条")
        # 类型统计
        from collections import Counter
        ct = Counter(a.get("action") for a in advisors_history)
        md.append(f"动作分布：{dict(ct)}")
        md.append("")
        md.append("_命中率需后续接入事后价才能算，这里只列出记录_")

    md.append("")
    md.append(f"_自动生成 by quant-learn / portfolio_alert.py + sim_executor.py + fusion_engine.py_")
    return "\n".join(md)


def call_iwiki_create(target_date, body_md):
    """调 iwiki helper 创建子页。策略：先 createDocument 占位页，再 saveDocument 写完整内容。避开命令行长 body 问题。"""
    sys.path.insert(0, str(ROOT / 'scripts'))
    from iwiki_helper import call_iwiki
    import re
    title = f"{target_date.year}年{target_date.month}月{target_date.day}日 市场分析（AI模拟版）"
    
    # Step 1: 创建占位页（body 仅 1 行）
    r1 = call_iwiki('createDocument',
                    spaceid=IWIKI_SPACE_ID,
                    parentid=IWIKI_PARENT_ID,
                    title=title,
                    contenttype="MD",
                    body=f'# {title}\n\n_生成中..._\n')
    
    if not r1.get('ok'):
        return r1
    
    # 解析 docid
    data_str = str(r1.get('data', ''))
    m = re.search(r'"docid":\s*(\d+)', data_str)
    if not m:
        return {'ok': False, 'error': f'无法从响应解析 docid: {data_str[:200]}'}
    new_docid = int(m.group(1))
    
    # Step 2: 分段追加 saveDocumentParts after。避免一次 saveDocument 传太长。
    # 首块 ≤1500 字符，后续每块≤2000。
    chunk_size = 1500
    chunks = [body_md[i:i+chunk_size] for i in range(0, len(body_md), chunk_size)]
    
    # 第一块用 saveDocument 覆写
    r2 = call_iwiki('saveDocument', docid=new_docid, title=title, body=chunks[0] if chunks else body_md)
    if not r2.get('ok'):
        return r2
    
    # 后续块用 saveDocumentParts after 追加
    for chunk in chunks[1:]:
        r3 = call_iwiki('saveDocumentParts', id=new_docid, title=title, after=chunk)
        if not r3.get('ok'):
            r2['warning'] = f'部分块追加失败: {r3}'
            break
    
    r2['docid'] = new_docid
    r2['url'] = f'https://iwiki.woa.com/p/{new_docid}'
    return r2


def generate_summary_for_wecom(target_date, account, positions, trades, nav_info):
    """精简版给企微群（markdown格式）"""
    lines = []
    lines.append(f"# 📊 {target_date.year}/{target_date.month}/{target_date.day} 复盘")
    lines.append("")
    lines.append(f"**总资产**: ¥{nav_info['total_value']:,.2f}（{nav_info['cumulative_return']:+.2f}%）")
    lines.append(f"**当日**: {nav_info['daily_return']:+.2f}% | **回撤**: {nav_info['max_drawdown']:+.2f}%")
    lines.append("")
    if trades:
        lines.append(f"**🤖 虚拟交易 {len(trades)} 笔**:")
        for t in trades[:5]:
            arrow = "🟢" if t['direction'] == 'BUY' else "🔴"
            lines.append(f"- {arrow} {t['stock_name']} {t['quantity']}股 @{t['price']:.2f}")
    else:
        lines.append("_当日无虚拟交易_")
    lines.append("")
    lines.append("**当前持仓**:")
    for p in positions:
        sign = "+" if p['pnl'] >= 0 else ""
        lines.append(f"- {p['stock_name']} {p['quantity']}股 → {sign}{p['pnl_pct']:.2f}%")
    return "\n".join(lines)


def main():
    target_date = get_target_date()
    logger.info(f"=== 开始复盘 {target_date} ===")
    
    account = fetch_account()
    positions = fetch_positions()
    trades = fetch_trades(target_date)
    
    # 写入当日净值
    nav_info = write_daily_nav(target_date, account, positions)
    navs_history = fetch_yesterday_nav(target_date)
    
    # 生成 iwiki markdown
    full_md = generate_markdown(target_date, account, positions, trades, nav_info, navs_history)
    
    # 保存到本地
    out_dir = ROOT / 'output' / 'reviews'
    out_dir.mkdir(parents=True, exist_ok=True)
    md_file = out_dir / f"{target_date.isoformat()}.md"
    md_file.write_text(full_md, encoding='utf-8')
    logger.info(f"✓ 已保存到本地: {md_file}")
    
    # 写入 iwiki
    try:
        r = call_iwiki_create(target_date, full_md)
        if r.get('ok'):
            logger.info(f"✓ iwiki 写入成功: {str(r.get('data'))[:200]}")
        else:
            logger.error(f"✗ iwiki 写入失败: {r}")
    except Exception as e:
        logger.error(f"✗ iwiki 写入异常: {e}")
    
    # 推送精简版到企微群
    summary = generate_summary_for_wecom(target_date, account, positions, trades, nav_info)
    if push_webhook(summary):
        logger.info("✓ 企微群推送成功")
    
    print(f"\n=== 复盘完成: {target_date} ===")
    print(f"总资产: ¥{nav_info['total_value']:,.2f}")
    print(f"当日: {nav_info['daily_return']:+.2f}% / 累计: {nav_info['cumulative_return']:+.2f}%")
    print(f"虚拟交易: {len(trades)} 笔")


if __name__ == "__main__":
    main()
