"""
scripts/morning_brief.py — 开盘前简报（PM Agent 用）

每天 9:25 集合竞价时跑一次：
1. 跑 5 个策略对全部 22 股 + 当前持仓做一次 decide
2. 输出明天信号汇总（每只股票各策略给出什么信号）
3. 重点提示：多策略一致看空/看多的股票
4. 推送给用户

这个脚本不下单，只是预报。
"""
from __future__ import annotations
import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vqlearn.services.history_loader import load_history
from vqlearn.strategies.pure_signals import ALL_STRATEGIES, get_strategy
from sim.realtime_price import fetch_sina_realtime

CONFIG_PATH = ROOT / 'vqlearn' / 'config' / 'portfolio.yaml'
DB_PATH = ROOT / 'data' / 'sim_live_mirror.db'


def get_position(code: str) -> tuple[int, float]:
    """从 sim_positions 拿当前持仓数量 + 成本"""
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT quantity, avg_cost FROM sim_positions WHERE stock_code=? AND quantity>0",
        (code,)
    ).fetchone()
    conn.close()
    return (row[0], row[1]) if row else (0, 0.0)


def push_to_wecom(content: str) -> bool:
    """推送内容到企微群机器人"""
    try:
        import yaml
        import urllib.request
        import json
        
        # 从config.local.yaml读取webhook URL
        local_cfg = ROOT / "config.local.yaml"
        if not local_cfg.exists():
            print("⚠️ 未找到 config.local.yaml，跳过 webhook 推送")
            return False
            
        data = yaml.safe_load(local_cfg.read_text(encoding="utf-8")) or {}
        webhook_url = (data.get("notifier") or {}).get("wecom_webhook")
        
        if not webhook_url:
            print("⚠️ 未配置 wecom_webhook，跳过 webhook 推送")
            return False
        
        # 构建markdown消息
        body = json.dumps({
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }).encode("utf-8")
        
        req = urllib.request.Request(
            webhook_url, 
            data=body,
            headers={"Content-Type": "application/json"}
        )
        
        resp = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
        ok = '"errcode":0' in resp
        
        if ok:
            print("✅ webhook 推送成功")
        else:
            print(f"⚠️ webhook 返回异常: {resp}")
            
        return ok
        
    except Exception as e:
        print(f"❌ webhook 推送失败: {e}")
        return False


def main():
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding='utf-8'))
    holdings = cfg.get('holdings', []) or []
    watchlist = cfg.get('watchlist', []) or []
    items = holdings + watchlist
    
    today = datetime.now()
    end = (today - timedelta(days=1)).strftime('%Y-%m-%d')
    start = (today - timedelta(days=180)).strftime('%Y-%m-%d')

    # 拉所有股票的实时价
    codes = [it['symbol'] for it in items]
    print(f"📡 拉 {len(codes)} 只股票实时行情...")
    realtime = fetch_sina_realtime(codes)

    # 对每只股票跑 5 个策略
    results = []
    for it in items:
        code = it['symbol']
        name = it.get('name', code)
        rules = it.get('rules') or {}
        rt = realtime.get(code)
        if not rt or rt.get('price', 0) <= 0:
            continue
        price = rt['price']
        position, avg_cost = get_position(code)

        bars = load_history(code, start, end)
        if bars.empty or len(bars) < 30:
            continue

        # 拼上今日实时
        today_row = pd.DataFrame([{
            'date': today.strftime('%Y-%m-%d'),
            'open': rt.get('open', price),
            'high': rt.get('high', price),
            'low': rt.get('low', price),
            'close': price,
            'volume': rt.get('volume', 0),
        }])
        for col in ['amount', 'turnover', 'pct']:
            if col in bars.columns:
                today_row[col] = 0
        full_bars = pd.concat([bars, today_row], ignore_index=True)

        signals = {}
        for sid in ALL_STRATEGIES:
            try:
                s = get_strategy(sid)
                sig = s.decide(full_bars, position, rules)
                signals[sid] = sig
            except Exception as e:
                signals[sid] = None

        # 计票
        buy_votes = sum(1 for s in signals.values() if s and s.action.startswith('BUY'))
        sell_votes = sum(1 for s in signals.values() if s and s.action.startswith('SELL'))

        results.append({
            'code': code,
            'name': name,
            'price': price,
            'position': position,
            'avg_cost': avg_cost,
            'pnl_pct': ((price - avg_cost) / avg_cost * 100) if avg_cost else None,
            'buy_votes': buy_votes,
            'sell_votes': sell_votes,
            'signals': signals,
            'is_holding': position > 0,
        })

    # 输出
    print(f"\n{'='*80}")
    print(f"☀️ {today.strftime('%Y-%m-%d')} 开盘前简报 - 多策略信号")
    print(f"{'='*80}\n")

    # 强烈卖出（持仓 + 多策略卖出）
    strong_sells = [r for r in results if r['is_holding'] and r['sell_votes'] >= 3]
    if strong_sells:
        print(f"🚨 强烈卖出建议（持仓且 ≥3 策略一致看空）：{len(strong_sells)} 只\n")
        for r in strong_sells:
            print(f"  📌 {r['code']} {r['name']} 现价 {r['price']:.2f} | 持仓 {r['position']}股@{r['avg_cost']:.2f} ({r['pnl_pct']:+.2f}%)")
            for sid, sig in r['signals'].items():
                if sig and sig.action != 'NO_ACTION':
                    icon = '🔴' if sig.action.startswith('SELL') else '🟢'
                    print(f"    {icon} {sid}: {sig.action} - {sig.rule_name}")
            print()

    # 强烈买入（≥3 策略一致看多）
    strong_buys = [r for r in results if not r['is_holding'] and r['buy_votes'] >= 3]
    if strong_buys:
        print(f"🟢 强烈买入建议（无持仓且 ≥3 策略一致看多）：{len(strong_buys)} 只\n")
        for r in strong_buys:
            print(f"  📌 {r['code']} {r['name']} 现价 {r['price']:.2f}")
            for sid, sig in r['signals'].items():
                if sig and sig.action != 'NO_ACTION':
                    print(f"    🟢 {sid}: {sig.action} - {sig.rule_name}")
            print()

    # 弱信号（1-2 票）
    weak_sells = [r for r in results if r['is_holding'] and 1 <= r['sell_votes'] <= 2]
    weak_buys = [r for r in results if not r['is_holding'] and 1 <= r['buy_votes'] <= 2]
    if weak_sells:
        print(f"\n🟡 弱卖出信号（持仓且 1-2 策略看空）：{len(weak_sells)} 只")
        for r in weak_sells:
            sells = [sid for sid, sig in r['signals'].items() if sig and sig.action.startswith('SELL')]
            print(f"  · {r['code']} {r['name']} ({r['pnl_pct']:+.2f}%): {','.join(sells)}")
    if weak_buys:
        print(f"\n🟡 弱买入信号（无持仓且 1-2 策略看多）：{len(weak_buys)} 只")
        for r in weak_buys:
            buys = [sid for sid, sig in r['signals'].items() if sig and sig.action.startswith('BUY')]
            print(f"  · {r['code']} {r['name']}: {','.join(buys)}")

    # 全静默
    silent = [r for r in results if r['buy_votes'] == 0 and r['sell_votes'] == 0]
    print(f"\n💤 无信号：{len(silent)} 只")

    # 总结
    print(f"\n{'='*80}")
    print(f"📊 总结")
    print(f"{'='*80}")
    print(f"  扫描股票：{len(results)} 只")
    print(f"  强卖：{len(strong_sells)} 只 | 弱卖：{len(weak_sells)} 只")
    print(f"  强买：{len(strong_buys)} 只 | 弱买：{len(weak_buys)} 只")
    print(f"  静默：{len(silent)} 只")
    
    # 返回报告内容（用于webhook推送）
    import io
    old_stdout = sys.stdout
    sys.stdout = captured_output = io.StringIO()
    
    try:
        # 重新输出报告内容到字符串
        print(f"## ☀️ 开盘前简报 {today.strftime('%Y-%m-%d %H:%M')}\n")
        
        if strong_sells:
            print(f"🚨 强烈卖出建议（持仓且 ≥3 策略一致看空）：{len(strong_sells)} 只\n")
            for r in strong_sells:
                print(f"  📌 {r['code']} {r['name']} 现价 {r['price']:.2f} | 持仓 {r['position']}股@{r['avg_cost']:.2f} ({r['pnl_pct']:+.2f}%)")
                for sid, sig in r['signals'].items():
                    if sig and sig.action != 'NO_ACTION':
                        icon = '🔴' if sig.action.startswith('SELL') else '🟢'
                        print(f"    {icon} {sid}: {sig.action} - {sig.rule_name}")
                print()
        
        if strong_buys:
            print(f"🟢 强烈买入建议（无持仓且 ≥3 策略一致看多）：{len(strong_buys)} 只\n")
            for r in strong_buys:
                print(f"  📌 {r['code']} {r['name']} 现价 {r['price']:.2f}")
                for sid, sig in r['signals'].items():
                    if sig and sig.action != 'NO_ACTION':
                        print(f"    🟢 {sid}: {sig.action} - {sig.rule_name}")
                print()
        
        if weak_sells:
            print(f"\n🟡 弱卖出信号（持仓且 1-2 策略看空）：{len(weak_sells)} 只")
            for r in weak_sells:
                sells = [sid for sid, sig in r['signals'].items() if sig and sig.action.startswith('SELL')]
                print(f"  · {r['code']} {r['name']} ({r['pnl_pct']:+.2f}%): {','.join(sells)}")
        if weak_buys:
            print(f"\n🟡 弱买入信号（无持仓且 1-2 策略看多）：{len(weak_buys)} 只")
            for r in weak_buys:
                buys = [sid for sid, sig in r['signals'].items() if sig and sig.action.startswith('BUY')]
                print(f"  · {r['code']} {r['name']}: {','.join(buys)}")
        
        print(f"\n💤 无信号：{len(silent)} 只")
        
        return captured_output.getvalue()
        
    finally:
        sys.stdout = old_stdout


if __name__ == '__main__':
    report = main()
    
    if report and report.strip():
        # 推送到企微
        if push_to_wecom(report):
            print("✅ 开盘前简报已推送到企微群")
        else:
            print("⚠️ 推送失败，请检查配置")
    else:
        print("ℹ️ 无内容可推送")
