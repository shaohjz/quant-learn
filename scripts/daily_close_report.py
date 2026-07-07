"""
scripts/daily_close_report.py - 收盘交易日报

每天15:05运行，汇总今日交易情况，通过 webhook 推送到企微。
"""
import sys, json, os
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def _load_webhook():
    """从配置读取企微 Webhook URL（与 portfolio_alert.py 一致）。"""
    try:
        import yaml
        # 1) config.local.yaml notify.wecom_webhook
        local_cfg = ROOT / 'config.local.yaml'
        if local_cfg.exists():
            with open(local_cfg, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            url = (cfg.get('notify') or {}).get('wecom_webhook', '') or ''
            if url and '***' not in url and 'YOUR_KEY' not in url:
                return url
        # 2) config.yaml notify.wecom_webhook
        cfg_path = ROOT / 'config.yaml'
        if cfg_path.exists():
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            url = (cfg.get('notify') or {}).get('wecom_webhook', '') or ''
            if url and '***' not in url and 'YOUR_KEY' not in url:
                return url
        # 3) config.local.yaml notifier.wecom_webhook（旧路径）
        if local_cfg.exists():
            with open(local_cfg, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            url = (cfg.get('notifier') or {}).get('wecom_webhook', '') or ''
            if url and '***' not in url and 'YOUR_KEY' not in url:
                return url
        # 4) 环境变量
        url = os.environ.get('WECOM_WEBHOOK', '') or ''
        if url:
            return url
        return ''
    except Exception:
        return ''


def push_webhook(content: str) -> bool:
    """推送 markdown 消息到企微群机器人。"""
    url = _load_webhook()
    if not url:
        print("❌ Webhook URL 未配置")
        return False
    import urllib.request
    payload = json.dumps({
        "msgtype": "markdown",
        "markdown": {"content": content}
    }).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=payload, method='POST')
        req.add_header('Content-Type', 'application/json')
        resp = urllib.request.urlopen(req, timeout=10).read().decode()
        ok = '"errcode":0' in resp
        if ok:
            print("✅ 收盘日报推送成功")
        else:
            print(f"⚠️ 推送返回异常: {resp}")
        return ok
    except Exception as e:
        print(f"❌ 推送失败: {e}")
        return False


def build_report() -> str:
    """生成收盘日报 markdown 文本。"""
    import sqlite3
    db = ROOT / 'data' / 'sim_live_mirror.db'
    today = datetime.now().strftime('%Y-%m-%d')

    conn = sqlite3.connect(db)
    c = conn.cursor()

    # 账户信息
    c.execute('SELECT cash, total_value FROM sim_account WHERE id=1')
    acct = c.fetchone()
    cash = float(acct[0]) if acct else 0
    total = float(acct[1]) if acct else 0
    pnl = total - 100000.0
    pnl_pct = pnl / 100000.0 * 100

    # 今日交易
    c.execute("""
        SELECT trade_time, stock_code, stock_name, direction, price, quantity, amount, signal_reason
        FROM sim_trades WHERE account_id=1 AND trade_date=? ORDER BY trade_time
    """, (today,))
    trades = c.fetchall()

    # 当前持仓
    c.execute("""
        SELECT stock_code, stock_name, quantity, avg_cost, current_price, market_value, pnl, pnl_pct
        FROM sim_positions WHERE account_id=1 AND quantity > 0 ORDER BY market_value DESC
    """)
    positions = c.fetchall()

    # 今日触发信号（从 alert_state.json 读取，只显示买入/卖出类）
    state_file = OUTPUT_DIR / 'alert_state.json'
    triggered_today = []
    if state_file.exists():
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            today_state = state.get(today, {})
            if isinstance(today_state, dict):
                for rule_id, info in today_state.items():
                    if not info.get('skipped'):
                        triggered_today.append((rule_id, info))
        except Exception as e:
            pass

    conn.close()

    # 构建 markdown
    lines = []
    lines.append(f'📊 **量化交易日报 — {today}**')
    lines.append('')
    lines.append(f'**账户概况**')
    lines.append(f'- 总资产：¥{total:,.2f}')
    lines.append(f'- 可用现金：¥{cash:,.2f}')
    lines.append(f'- 当日盈亏：¥{pnl:+,.2f}（{pnl_pct:+.2f}%）')
    lines.append('')

    if trades:
        lines.append(f'**今日交易（{len(trades)}笔）**')
        for t in trades:
            time, code, name, direction, price, qty, amount, reason = t
            emoji = '🟢' if direction == 'BUY' else '🔴'
            lines.append(f'- {emoji} {time} {name}（{code}）{direction} {qty}股 @ ¥{price:.2f}，金额¥{amount:.0f}')
            if reason:
                lines.append(f'  └ 原因：{reason}')
        lines.append('')

    if positions:
        lines.append(f'**当前持仓（{len(positions)}只）**')
        for p in positions:
            code, name, qty, cost, cur, mkt_val, pnl_val, pnl_pct_val = p
            emoji = '🟢' if pnl_val >= 0 else '🔴'
            lines.append(f'- {emoji} {name}（{code}）：{qty}股，成本¥{cost:.2f}，现价¥{cur:.2f}，盈亏{pnl_val:+,.2f}（{pnl_pct_val:+.2f}%）')
        lines.append('')
    else:
        lines.append('**当前持仓：无**')
        lines.append('')

    if triggered_today:
        lines.append(f'**今日触发信号（{len(triggered_today)}个）**')
        for rule_id, info in triggered_today[:10]:
            lines.append(f'- {rule_id} @ ¥{info.get("price", "?")}')
        lines.append('')

    # 明日关注
    lines.append('**明日关注**')
    lines.append(f'- 可用资金：¥{cash:,.2f}，可买入约 {int(cash / 10000)} 手（均价¥100以下股票）')
    lines.append(f'- 观察池：36只股票等待触发买入/卖出信号')
    lines.append('')
    lines.append('_本报告由量化系统自动生成_')

    return '\n'.join(lines)


if __name__ == '__main__':
    report = build_report()
    print(report)
    push_webhook(report)
