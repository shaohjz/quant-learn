"""
scripts/check_sampling_coverage.py — 检查盘中采样覆盖完整性

功能：
  - 读取 output/intraday_log.jsonl 当日快照
  - 检查是否覆盖上午盘（09:30-11:30）和下午盘（13:00-15:00）
  - 输出覆盖率报告
  - 覆盖率低时输出告警信息（供 cron 或主脚本调用）

用法：
  python scripts/check_sampling_coverage.py           # 检查今天
  python scripts/check_sampling_coverage.py 2026-06-09  # 检查指定日期
"""

import json, sys, pathlib, argparse
from datetime import datetime, date, time as dtime
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
INTRADAY_LOG = ROOT / "output" / "intraday_log.jsonl"

def check_coverage(check_date: date) -> dict:
    """检查指定日期的采样覆盖情况"""
    if not INTRADAY_LOG.exists():
        return {"error": "intraday_log.jsonl 不存在"}
    
    # 读取当日所有快照
    snapshots = []
    with open(INTRADAY_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                ts = datetime.fromisoformat(obj["ts"])
                if ts.date() == check_date:
                    snapshots.append(obj)
            except Exception:
                continue
    
    if not snapshots:
        return {
            "date": check_date.isoformat(),
            "total_samples": 0,
            "coverage": "none",
            "morning_samples": 0,
            "afternoon_samples": 0,
            "morning_covered": False,
            "afternoon_covered": False,
            "alert": True,
            "alert_msg": f"⚠️ {check_date} 无采样数据！请检查 portfolio_alert 任务是否正常运行。"
        }
    
    # 按时间段分类
    morning = []  # 09:30-11:30
    afternoon = []  # 13:00-15:00
    
    for snap in snapshots:
        ts = datetime.fromisoformat(snap["ts"])
        t = ts.time()
        if dtime(9, 30) <= t <= dtime(11, 30):
            morning.append(snap)
        elif dtime(13, 0) <= t <= dtime(15, 0):
            afternoon.append(snap)
    
    # 计算覆盖率
    total_samples = len(snapshots)
    morning_count = len(morning)
    afternoon_count = len(afternoon)
    
    # 理想情况：每10分钟采样一次
    # 上午盘 2小时 = 12个采样点
    # 下午盘 2小时 = 12个采样点
    morning_coverage = morning_count / 12 * 100 if morning_count > 0 else 0
    afternoon_coverage = afternoon_count / 12 * 100 if afternoon_count > 0 else 0
    total_coverage = (morning_count + afternoon_count) / 24 * 100
    
    # 判断是否覆盖完整
    morning_covered = morning_coverage >= 80  # 至少80%覆盖率
    afternoon_covered = afternoon_coverage >= 80
    overall_covered = total_coverage >= 80
    
    result = {
        "date": check_date.isoformat(),
        "total_samples": total_samples,
        "morning_samples": morning_count,
        "afternoon_samples": afternoon_count,
        "morning_coverage": f"{morning_coverage:.1f}%",
        "afternoon_coverage": f"{afternoon_coverage:.1f}%",
        "total_coverage": f"{total_coverage:.1f}%",
        "morning_covered": morning_covered,
        "afternoon_covered": afternoon_covered,
        "overall_covered": overall_covered,
        "alert": not overall_covered,
    }
    
    if not morning_covered:
        result["alert_msg"] = f"⚠️ {check_date} 上午盘采样覆盖不足（{morning_coverage:.1f}%），仅 {morning_count} 个采样点。请检查任务计划程序是否正常。"
    elif not afternoon_covered:
        result["alert_msg"] = f"⚠️ {check_date} 下午盘采样覆盖不足（{afternoon_coverage:.1f}%），仅 {afternoon_count} 个采样点。请检查任务计划程序是否正常。"
    
    return result

def main():
    parser = argparse.ArgumentParser(description="检查盘中采样覆盖完整性")
    parser.add_argument("date", nargs="?", default=datetime.now().date().isoformat(), help="检查日期 (YYYY-MM-DD)，默认今天")
    args = parser.parse_args()
    
    try:
        check_date = date.fromisoformat(args.date)
    except ValueError:
        print(f"❌ 日期格式错误: {args.date}，应为 YYYY-MM-DD")
        return 1
    
    result = check_coverage(check_date)
    
    if "error" in result:
        print(f"❌ {result['error']}")
        return 1
    
    # 输出报告
    print(f"📊 {result['date']} 采样覆盖报告")
    print(f"=" * 50)
    print(f"总采样数: {result['total_samples']}")
    print(f"上午盘 (09:30-11:30): {result['morning_samples']} 个采样 ({result['morning_coverage']})")
    print(f"下午盘 (13:00-15:00): {result['afternoon_samples']} 个采样 ({result['afternoon_coverage']})")
    print(f"总覆盖率: {result['total_coverage']}")
    print(f"上午盘覆盖: {'✅' if result['morning_covered'] else '❌'}")
    print(f"下午盘覆盖: {'✅' if result['afternoon_covered'] else '❌'}")
    
    if result["alert"]:
        print(f"\n{result['alert_msg']}")
        return 1  # 非零退出码表示需要告警
    
    print(f"\n✅ 采样覆盖完整")
    return 0

if __name__ == "__main__":
    sys.exit(main())
