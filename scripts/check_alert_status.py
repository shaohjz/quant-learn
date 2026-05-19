"""
scripts/check_alert_status.py — 查看盘中监控运行状态

用法：
  python scripts/check_alert_status.py        # 看最近 10 次运行
  python scripts/check_alert_status.py --tail 50    # 看最近 50 次
  python scripts/check_alert_status.py --today      # 今日所有快照
"""
import json
import sys
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = ROOT / "output" / "portfolio_alert.log"
INTRADAY_LOG = ROOT / "output" / "intraday_log.jsonl"
STATE_FILE = ROOT / "output" / "alert_state.json"


def show_recent_snapshots(n=10, today_only=False):
    """显示最近 n 次行情快照"""
    if not INTRADAY_LOG.exists():
        print("⚠️ 还没有任何快照（intraday_log.jsonl 不存在）")
        return
    
    lines = INTRADAY_LOG.read_text(encoding="utf-8").strip().split("\n")
    snapshots = []
    for line in lines:
        try:
            d = json.loads(line)
            # 新格式有 run_id，老格式没有
            if "run_id" in d or "prices" in d:
                snapshots.append(d)
        except:
            continue
    
    if today_only:
        today_str = date.today().isoformat()
        snapshots = [s for s in snapshots if s.get("ts", "").startswith(today_str)]
    else:
        snapshots = snapshots[-n:]
    
    if not snapshots:
        print(f"⚠️ {'今日' if today_only else f'最近 {n} 次'}没有数据")
        return
    
    print(f"\n📊 {'今日所有' if today_only else f'最近 {len(snapshots)} 次'}行情快照：\n")
    print(f"{'时间':<10}", end="")
    
    # 列出所有出现过的股票代码
    all_codes = set()
    for s in snapshots:
        all_codes.update(s.get("prices", {}).keys())
    codes = sorted(all_codes)
    for c in codes:
        print(f"{c:<10}", end="")
    print()
    print("-" * (10 + 10 * len(codes)))
    
    for s in snapshots:
        ts = s.get("ts", "")
        if ts:
            try:
                t = datetime.fromisoformat(ts).strftime("%H:%M:%S")
            except:
                t = ts[:8]
        else:
            t = "??"
        print(f"{t:<10}", end="")
        prices = s.get("prices", {})
        for c in codes:
            v = prices.get(c, 0)
            if isinstance(v, dict):
                v = v.get("price", 0)
            print(f"{v:>9.2f} ", end="")
        print()


def show_today_alerts():
    """显示今日已触发的阈值"""
    if not STATE_FILE.exists():
        print("\n⚠️ 还没有触发过任何阈值")
        return
    
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    today_str = date.today().isoformat()
    today = state.get(today_str, {})
    
    if not today:
        print(f"\n✅ 今日 ({today_str}) 暂无任何阈值被触发（一切正常）")
        return
    
    print(f"\n🔔 今日 ({today_str}) 已触发 {len(today)} 条阈值：\n")
    for rule_id, info in sorted(today.items(), key=lambda x: x[1].get("triggered_at", "")):
        print(f"  {info.get('triggered_at', '??')}  {rule_id:<30} 价={info.get('price', 0):.2f}  阈值={info.get('trigger', 0):.2f}")


def show_log_tail(n=20):
    """显示最近运行日志"""
    if not LOG_FILE.exists():
        print("⚠️ 还没有日志文件")
        return
    
    lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
    print(f"\n📜 最近 {min(n, len(lines))} 行日志：\n")
    for line in lines[-n:]:
        print(f"  {line}")


def main():
    args = sys.argv[1:]
    today_only = "--today" in args
    tail_idx = args.index("--tail") if "--tail" in args else -1
    n = int(args[tail_idx + 1]) if tail_idx >= 0 and tail_idx + 1 < len(args) else 10
    
    print("=" * 70)
    print(f"  📊 盘中监控状态 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    show_today_alerts()
    show_recent_snapshots(n=n, today_only=today_only)
    show_log_tail(n=15)
    
    print("\n" + "=" * 70)
    print("  💡 用法:")
    print("     python scripts/check_alert_status.py            # 默认看最近 10 次")
    print("     python scripts/check_alert_status.py --tail 30  # 最近 30 次")
    print("     python scripts/check_alert_status.py --today    # 今天所有快照")
    print("=" * 70)


if __name__ == "__main__":
    main()
