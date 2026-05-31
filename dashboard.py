"""
dashboard.py — 本地小看板
启动：python dashboard.py
访问：http://0.0.0.0:8080
"""

import os
import sys
import sqlite3
import yaml
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, render_template_string, request, send_file

app = Flask(__name__)

# ── HTML 模板 ────────────────────────────────────────────────────────────────
HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>quant-learn 看板</title>
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#0f1419;color:#e6e6e6;margin:0;padding:24px;
       max-width:1100px;margin-left:auto;margin-right:auto}
  h1{margin:0 0 8px;font-size:24px}
  .meta{color:#8a8f99;font-size:13px;margin-bottom:24px}
  .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px}
  .card{background:#1a1f2e;border-radius:8px;padding:18px;border:1px solid #2d3548}
  .card .label{color:#8a8f99;font-size:12px;text-transform:uppercase;letter-spacing:.5px}
  .card .value{font-size:24px;font-weight:600;margin-top:6px}
  .card.pnl-up .value{color:#4ade80}
  .card.pnl-down .value{color:#f87171}
  .section{background:#1a1f2e;border-radius:8px;padding:18px;border:1px solid #2d3548;
           margin-bottom:16px}
  .section h2{margin:0 0 12px;font-size:16px}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #2d3548}
  th{color:#8a8f99;font-weight:500;font-size:11px;text-transform:uppercase}
  tr:hover{background:#222837}
  .buy{color:#4ade80}.sell{color:#f87171}
  .nav-img{max-width:100%;border-radius:6px;display:block}
  .empty{color:#6c7280;text-align:center;padding:32px;font-style:italic}
  .refresh{position:fixed;top:20px;right:20px;background:#3b82f6;color:white;
           border:none;border-radius:6px;padding:8px 14px;cursor:pointer;font-size:13px}
  .tabs{margin-bottom:16px}
  .tabs a{color:#8a8f99;text-decoration:none;padding:6px 12px;border-radius:4px;margin-right:8px;font-size:13px}
  .tabs a.active{background:#1a1f2e;color:#e6e6e6}
</style>
</head>
<body>
<button class="refresh" onclick="location.reload()">🔄 刷新</button>

<div class="tabs">
  <a href="/" class="{{ 'active' if request.path=='/' else '' }}">📊 交易看板</a>
  <a href="/pm" class="{{ 'active' if request.path=='/pm' else '' }}">📋 PM 看板</a>
</div>

<h1>📊 quant-learn {{ '模拟盘' if account_id==1 else '实盘' }}</h1>
<div class="meta">{{ now }} · 数据来源 {{ db_name }}</div>

<div class="grid">
  <div class="card {{ 'pnl-up' if account.pnl >= 0 else 'pnl-down' }}">
    <div class="label">总资产</div>
    <div class="value">¥{{ '%.2f'|format(account.total_value) }}</div>
  </div>
  <div class="card">
    <div class="label">可用资金</div>
    <div class="value">¥{{ '%.2f'|format(account.cash) }}</div>
  </div>
  <div class="card {{ 'pnl-up' if account.pnl >= 0 else 'pnl-down' }}">
    <div class="label">总盈亏</div>
    <div class="value">¥{{ '%+.2f'|format(account.pnl) }}</div>
  </div>
  <div class="card {{ 'pnl-up' if account.pnl >= 0 else 'pnl-down' }}">
    <div class="label">累计收益率</div>
    <div class="value">{{ '%+.2f'|format(account.pnl_pct * 100) }}%</div>
  </div>
</div>

<div class="section">
  <h2>📦 当前持仓</h2>
  {% if positions %}
  <table>
    <tr><th>股票</th><th>数量</th><th>成本</th><th>现价</th><th>市值</th><th>盈亏</th><th>%</th></tr>
    {% for p in positions %}
    <tr>
      <td>{{ p.stock_name }}({{ p.stock_code }})</td>
      <td>{{ p.quantity }}</td>
      <td>¥{{ '%.4f'|format(p.avg_cost) }}</td>
      <td>¥{{ '%.4f'|format(p.current_price or 0) }}</td>
      <td>¥{{ '%.2f'|format(p.market_value or 0) }}</td>
      <td class="{{ 'buy' if (p.pnl or 0) >= 0 else 'sell' }}">¥{{ '%+.2f'|format(p.pnl or 0) }}</td>
      <td class="{{ 'buy' if (p.pnl_pct or 0) >= 0 else 'sell' }}">{{ '%+.2f'|format((p.pnl_pct or 0) * 100) }}%</td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <div class="empty">空仓中</div>
  {% endif %}
</div>

<div class="section">
  <h2>📋 最近交易（最多 30 条）</h2>
  {% if trades %}
  <table>
    <tr><th>日期</th><th>方向</th><th>股票</th><th>数量</th><th>价格</th><th>金额</th><th>来源</th><th>信号</th></tr>
    {% for t in trades %}
    <tr>
      <td>{{ t.trade_date }}</td>
      <td class="{{ 'buy' if t.direction == 'BUY' else 'sell' }}">
        {{ '🟢买' if t.direction == 'BUY' else '🔴卖' }}
      </td>
      <td>{{ t.stock_name }}({{ t.stock_code }})</td>
      <td>{{ t.quantity }}</td>
      <td>¥{{ '%.4f'|format(t.price) }}</td>
      <td>¥{{ '%.2f'|format(t.amount) }}</td>
      <td>{{ t.broker or 'sim' }}</td>
      <td>{{ (t.signal_reason or '')[:40] }}</td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <div class="empty">尚无交易</div>
  {% endif %}
</div>

<div class="section">
  <h2>📈 净值曲线</h2>
  {% if has_chart %}
  <img class="nav-img" src="/nav-chart.png?t={{ ts }}" alt="净值曲线">
  {% else %}
  <div class="empty">净值数据不足，先跑一次 settle 生成</div>
  {% endif %}
</div>
</body>
</html>
"""


# ── PM 看板 HTML 模板 ──────────────────────────────────────────────────────────
PM_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>PM 看板 — quant-learn</title>
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#0f1419;color:#e6e6e6;padding:24px;max-width:1200px;
       margin-left:auto;margin-right:auto}
  h1{margin:0 0 16px;font-size:24px}
  .tabs{margin-bottom:16px}
  .tabs a{color:#8a8f99;text-decoration:none;padding:6px 12px;border-radius:4px;margin-right:8px;font-size:13px}
  .tabs a.active{background:#1a1f2e;color:#e6e6e6}
  .stats{display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap}
  .stat{background:#1a1f2e;padding:12px 18px;border-radius:8px;border:1px solid #2d3548}
  .stat .label{color:#8a8f99;font-size:12px}
  .stat .val{font-size:20px;font-weight:600;margin-top:4px}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #2d3548}
  th{color:#8a8f99;font-weight:500;font-size:11px;text-transform:uppercase}
  tr:hover{background:#222837}
  .badge{padding:2px 8px;border-radius:4px;font-size:12px;display:inline-block}
  .refresh{position:fixed;top:20px;right:20px;background:#3b82f6;color:white;
           border:none;border-radius:6px;padding:8px 14px;cursor:pointer;font-size:13px}
  a{color:#3b82f6;text-decoration:none}
</style>
</head>
<body>
<button class="refresh" onclick="location.reload()">🔄 刷新</button>
<div class="tabs">
  <a href="/" class="{{ 'active' if request.path=='/' else '' }}">📊 交易看板</a>
  <a href="/pm" class="{{ 'active' if request.path=='/pm' else '' }}">📋 PM 看板</a>
</div>
<h1>📋 PM 看板</h1>
<div class="stats">
  {% for s in ["open","pending","in_progress","testing","done","verified","reopened","closed"] %}
  <div class="stat">
    <div class="label">{{ {"open":"📋","pending":"⏳","in_progress":"🔧","testing":"🧪",
       "done":"✅","verified":"✔️","reopened":"🔄","closed":"🗄️"}[s] }} {{ s }}</div>
    <div class="val">{{ stats.get(s,0) }}</div>
  </div>
  {% endfor %}
</div>
<table>
  <tr><th>ID</th><th>状态</th><th>优先级</th><th>标题</th><th>创建时间</th><th>更新时间</th></tr>
  {% for t in tasks %}
  <tr>
    <td>{{ t.id }}</td>
    <td><span class="badge">{{ t.status }}</span></td>
    <td>{{ t.priority or '—' }}</td>
    <td>{{ t.title }}</td>
    <td>{{ (t.created_at or '')[:16] }}</td>
    <td>{{ (t.updated_at or '')[:16] }}</td>
  </tr>
  {% endfor %}
</table>
</body>
</html>
"""


# ── 数据获取 ─────────────────────────────────────────────────────────────────────
def _get_db_path():
    """返回 sim_live_mirror.db 的路径（实际有数据的库）"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sim_live_mirror.db")


def _fetch_dashboard_data(account_id: int = 1):
    """
    account_id=1 → learn 模拟盘（config.yaml 里 initial_cash=200000）
    account_id=2 → real 实盘
    """
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()

        # initial_cash 优先读 config.yaml（数据库里的可能不对）
        cfg = yaml.safe_load(open(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "config.yaml"), encoding="utf-8"))
        acct_key = "learn" if account_id == 1 else "real"
        initial = float(cfg.get("accounts", {}).get(acct_key, {}).get("initial_cash", 100000))

        cur.execute(
            "SELECT cash, total_value FROM sim_account WHERE id = ?",
            (account_id,))
        a = cur.fetchone()
        cash = float(a["cash"]) if a else 0
        total = float(a["total_value"]) if a else 0
        pnl = total - initial
        pnl_pct = (pnl / initial) if initial else 0

        account = {
            "initial_cash": initial, "cash": cash,
            "total_value": total, "pnl": pnl, "pnl_pct": pnl_pct,
        }

        cur.execute(
            "SELECT stock_code, stock_name, quantity, avg_cost, current_price, "
            "market_value, pnl, pnl_pct FROM sim_positions "
            "WHERE account_id = ? AND quantity > 0",
            (account_id,))
        positions = [dict(r) for r in cur.fetchall()]

        cur.execute(
            "SELECT trade_date, direction, stock_code, stock_name, quantity, "
            "price, amount, broker, signal_reason "
            "FROM sim_trades WHERE account_id = ? "
            "ORDER BY id DESC LIMIT 30",
            (account_id,))
        trades = [dict(r) for r in cur.fetchall()]

    finally:
        conn.close()

    return account, positions, trades


def _fetch_pm_data():
    """从 data/pm.db 读取任务列表和统计"""
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pm.db")
    if not os.path.exists(db_path):
        return {"stats": {}, "tasks": []}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, status, priority, created_at, updated_at "
            "FROM tasks ORDER BY created_at DESC LIMIT 50")
        tasks = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status")
        stats = {r["status"]: r["cnt"] for r in cur.fetchall()}
    finally:
        conn.close()
    return {"stats": stats, "tasks": tasks}


# ── 路由 ───────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    account_id = int(request.args.get("account", 1))
    account, positions, trades = _fetch_dashboard_data(account_id)
    chart_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "output", "nav_chart.png")
    return render_template_string(
        HTML,
        account=account, positions=positions, trades=trades,
        has_chart=os.path.exists(chart_path),
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ts=int(datetime.now().timestamp()),
        account_id=account_id,
        db_name="sim_live_mirror.db",
        request=request,
    )


@app.route("/nav-chart.png")
def nav_chart():
    p = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "output", "nav_chart.png")
    if not os.path.exists(p):
        return "no chart", 404
    return send_file(p, mimetype="image/png")


@app.route("/api/summary")
def api_summary():
    account_id = int(request.args.get("account", 1))
    account, positions, trades = _fetch_dashboard_data(account_id)
    return jsonify({"account": account, "positions": positions, "trades": trades})


@app.route("/pm")
def pm_board():
    pm = _fetch_pm_data()
    return render_template_string(
        PM_HTML,
        stats=pm["stats"], tasks=pm["tasks"], request=request,
    )


@app.route("/api/pm")
def api_pm():
    return jsonify(_fetch_pm_data())


# ── 启动 ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 8080))
    print(f"🚀 看板：http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
