"""
lockup_alert.py — 解禁预警通知

功能：
  1. 扫描 watchlist + 持仓中所有股票的未来 90 天解禁
  2. 对 30 天内有解禁的发出预警
  3. 支持状态文件去重（已通知的不重复通知）

输出：output/lockup_alerts/YYYY-MM-DD_alert.json
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "a-stock-data-signals"))

from a_stock_data_signals import lockup_warning_signal, tencent_quote


# ── 状态文件：记录已通知过的解禁事件 ──
STATE_DIR = ROOT / "output" / "lockup_alerts"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / "notified_state.json"


def load_notified() -> set:
    """加载已通知过的解禁事件"""
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return set(data.get("notified", []))
        except Exception:
            return set()
    return set()


def save_notified(notified: set):
    """保存已通知过的解禁事件"""
    STATE_FILE.write_text(
        json.dumps({"notified": sorted(notified), "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_watchlist_codes() -> list[dict]:
    """加载所有需要监控的股票代码"""
    seen = set()
    stocks = []

    # 1. 长线观察
    notes_path = ROOT / "data" / "watchlist_notes.json"
    if notes_path.exists():
        data = json.loads(notes_path.read_text(encoding="utf-8"))
        for item in data.get("watchlist", []):
            code = item.get("code", "")
            if code and code not in seen:
                seen.add(code)
                stocks.append({"code": code, "name": item.get("name", ""), "source": "长线观察"})

    # 2. 每日 watchlist
    nw_dir = ROOT / "data" / "next_watchlists"
    if nw_dir.exists():
        files = sorted(nw_dir.glob("*.json"), reverse=True)
        if files:
            data = json.loads(files[0].read_text(encoding="utf-8"))
            for item in data.get("candidates", []):
                code = item.get("code", "")
                if code and code not in seen:
                    seen.add(code)
                    stocks.append({"code": code, "name": item.get("name", ""), "source": "每日观察"})

    # 3. 持仓
    holdings_path = ROOT / "data" / "real_holdings.json"
    if holdings_path.exists():
        data = json.loads(holdings_path.read_text(encoding="utf-8"))
        for item in data:
            code = item.get("code", "")
            if code and code not in seen:
                seen.add(code)
                stocks.append({"code": code, "name": item.get("name", ""), "source": "持仓"})

    return stocks


def check_lockups(forward_days: int = 90, alert_days: int = 30) -> dict:
    """
    检查所有监控股票的解禁情况。
    forward_days: 向前看的天数
    alert_days: 在此天数内的解禁触发预警
    """
    stocks = load_watchlist_codes()
    notified = load_notified()
    new_alerts = []
    all_results = []

    print(f"检查 {len(stocks)} 只股票的解禁情况...")

    for i, s in enumerate(stocks):
        code = s["code"]
        print(f"  [{i+1}/{len(stocks)}] {code} {s['name']}...", end="")

        try:
            result = lockup_warning_signal(code)
        except Exception as e:
            print(f" ❌ {e}")
            continue

        result["source"] = s["source"]
        result["name"] = s["name"]
        all_results.append(result)

        if result.get("has_upcoming"):
            # 检查是否有 30 天内的解禁
            today = datetime.now()
            for u in result["upcoming"]:
                try:
                    unlock_date = datetime.strptime(str(u["date"])[:10], "%Y-%m-%d")
                    days_to = (unlock_date - today).days
                    if 0 <= days_to <= alert_days:
                        # 生成唯一 key 去重
                        event_key = f"{code}|{u['date']}|{u['type']}"
                        if event_key not in notified:
                            new_alerts.append({
                                "code": code,
                                "name": s["name"],
                                "source": s["source"],
                                "date": u["date"],
                                "type": u["type"],
                                "shares": u["shares"],
                                "ratio": u["ratio"],
                                "days_to": days_to,
                                "event_key": event_key,
                            })
                            notified.add(event_key)
                        print(f" ⚠️ 解禁! {u['date']} {u['type']}")
                    else:
                        print(f" 🔓 {days_to}天后解禁 {u['type']}")
                except Exception:
                    pass
        else:
            print(" ✅")

    # 保存已通知状态
    save_notified(notified)

    # 按解禁日期排序
    new_alerts.sort(key=lambda a: a["days_to"])

    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_checked": len(stocks),
        "new_alerts": new_alerts,
        "alert_count": len(new_alerts),
        "all_results": all_results,
    }

    # 保存报告
    path = STATE_DIR / f"{report['date']}_alert.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"\n[OK] 解禁预警报告已保存: {path}")

    return report


def format_alert_text(report: dict) -> str:
    """格式化为可读文本"""
    lines = []
    lines.append(f"🔓 解禁预警 — {report.get('date', '未知')}")
    lines.append(f"检查 {report['total_checked']} 只股票")
    lines.append("=" * 60)

    if report["alert_count"] == 0:
        lines.append("\n✅ 30 天内无异动解禁")
        return "\n".join(lines)

    lines.append(f"\n⚠️ 发现 {report['alert_count']} 条解禁预警:\n")

    for a in report["new_alerts"]:
        shares_str = f"{a['shares']/10000:.0f}万" if a['shares'] else "未知"
        ratio_str = f"{a['ratio']:.1%}" if a.get('ratio') else ""
        lines.append(f"  🚨 {a['code']} {a['name']} ({a['source']})")
        lines.append(f"     解禁日: {a['date']} (还有 {a['days_to']} 天)")
        lines.append(f"     类型: {a['type']}")
        lines.append(f"     数量: {shares_str} {ratio_str}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    forward = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    alert = int(sys.argv[2]) if len(sys.argv) > 2 else 30

    report = check_lockups(forward_days=forward, alert_days=alert)
    text = format_alert_text(report)
    print("\n" + text)
