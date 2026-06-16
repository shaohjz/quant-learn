#!/usr/bin/env python3
"""
数据新鲜度检查脚本
====================
检查 data/*.csv 是否更新到最近交易日。
若发现数据过期，自动触发 backfill_data.py 补录，并通过企微 Webhook 告警。

使用方法:
    python scripts/check_data_freshness.py          # 检查并自动修复
    python scripts/check_data_freshness.py --check-only  # 仅检查，不修复
    python scripts/check_data_freshness.py --force-backfill  # 强制补录最近5个交易日
"""

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Tuple

WORKSPACE = Path(__file__).resolve().parent.parent
DATA_DIR = WORKSPACE / "data"
PM_DATA_DIR = WORKSPACE / "pm" / "data"
OUTPUT_DIR = WORKSPACE / "output"

PM_DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_last_date(csv_file: Path):
    """获取 CSV 文件的最后日期"""
    try:
        import pandas as pd
        df = pd.read_csv(csv_file)
        if 'date' not in df.columns or df.empty:
            return None
        last = str(df['date'].max())
        return datetime.strptime(last[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def check_all_files() -> Tuple[List[Tuple[str, date]], date | None]:
    """检查所有 CSV 文件的数据新鲜度"""
    csv_files = sorted(DATA_DIR.glob("*.csv"))
    today = date.today()
    
    stale_files = []
    latest_date = None
    
    for csv_file in csv_files:
        last_date = get_last_date(csv_file)
        if last_date is None:
            stale_files.append((csv_file.name, None))
            continue
        
        if latest_date is None or last_date > latest_date:
            latest_date = last_date
        
        # 如果最后日期 < 今天-1天，且今天是工作日，认为过期
        if (today - last_date).days > 1 and today.weekday() < 5:
            stale_files.append((csv_file.name, last_date))
    
    return stale_files, latest_date


def send_wecom_alert(msg: str) -> bool:
    """发送企微 Webhook 告警"""
    try:
        sys.path.insert(0, str(WORKSPACE / "scripts"))
        from wecom_webhook import send_markdown, WECOM_WEBHOOK_URL
        
        if not WECOM_WEBHOOK_URL:
            print("  ⚠️ WECOM_WEBHOOK_URL 未配置，跳过企微告警")
            return False
        
        send_markdown(msg)
        print("  ✓ 企微告警已发送")
        return True
    except Exception as e:
        print(f"  ⚠️ 企微告警发送失败: {e}")
        return False


def auto_backfill(start_date: str, end_date: str) -> bool:
    """自动触发 backfill_data.py 补录数据"""
    backfill_script = WORKSPACE / "scripts" / "backfill_data.py"
    if not backfill_script.exists():
        print(f"  ❌ backfill_data.py 不存在: {backfill_script}")
        return False
    
    print(f"  🔄 自动补录数据: {start_date} ~ {end_date}")
    try:
        result = subprocess.run(
            [sys.executable, str(backfill_script)],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode == 0:
            print(f"  ✓ 自动补录成功")
            return True
        else:
            print(f"  ❌ 自动补录失败 (exit={result.returncode})")
            print(f"  stderr: {result.stderr[-500:]}")
            return False
    except subprocess.TimeoutExpired:
        print(f"  ❌ 自动补录超时（>600s）")
        return False
    except Exception as e:
        print(f"  ❌ 自动补录异常: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="数据新鲜度检查")
    parser.add_argument("--check-only", action="store_true", help="仅检查，不自动修复")
    parser.add_argument("--force-backfill", action="store_true", help="强制补录最近5个交易日")
    parser.add_argument("--max-stale-days", type=int, default=3, help="允许的最大过期天数（默认3天）")
    args = parser.parse_args()
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] 数据新鲜度检查开始...")
    print(f"  工作目录: {WORKSPACE}")
    
    # 1. 检查所有文件
    stale_files, latest_date = check_all_files()
    today = date.today()
    
    print(f"\n  今天: {today}")
    print(f"  数据最后日期: {latest_date or '未知'}")
    
    if latest_date:
        delta = (today - latest_date).days
        print(f"  差距: {delta} 天")
    
    print(f"\n  过期文件数: {len(stale_files)}")
    for fname, last_date in stale_files[:5]:
        print(f"    - {fname}: {last_date or '无数据'}")
    if len(stale_files) > 5:
        print(f"    ... 还有 {len(stale_files) - 5} 个")
    
    # 2. 判断是否需要修复
    need_fix = False
    if args.force_backfill:
        need_fix = True
        print("\n  ⚡ --force-backfill 模式，强制执行补录")
    elif stale_files:
        if latest_date and (today - latest_date).days > args.max_stale_days:
            need_fix = True
            print(f"\n  ⚠️ 数据已过期 {(today - latest_date).days} 天，需要补录")
    
    # 3. 自动修复
    if need_fix and not args.check_only:
        if latest_date:
            start_dt = latest_date + timedelta(days=1)
        else:
            start_dt = today - timedelta(days=30)
        start_date = start_dt.strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")
        
        print(f"\n  📅 补录范围: {start_date} ~ {end_date}")
        
        success = auto_backfill(start_date, end_date)
        
        if success:
            stale_files2, latest_date2 = check_all_files()
            msg_lines = [
                "## ✅ 数据补录成功",
                f"**范围**: {start_date} ~ {end_date}",
                f"**最新数据日期**: {latest_date2}",
                f"**过期文件数**: {len(stale_files2)}",
                "_由 check_data_freshness.py 自动修复_",
            ]
            send_wecom_alert("\n".join(msg_lines))
        else:
            msg_lines = [
                "## ❌ 数据补录失败",
                f"**范围**: {start_date} ~ {end_date}",
                "请手动检查 `python scripts/backfill_data.py`",
                "_由 check_data_freshness.py 告警_",
            ]
            send_wecom_alert("\n".join(msg_lines))
    
    elif need_fix and args.check_only:
        print("\n  ℹ️ --check-only 模式，跳过自动修复")
        msg_lines = [
            "## ⚠️ 数据过期告警",
            f"**最新数据日期**: {latest_date}",
            f"**今天**: {today}",
            f"**过期文件数**: {len(stale_files)}",
            "请手动执行 `python scripts/backfill_data.py`",
            "_由 check_data_freshness.py 告警_",
        ]
        send_wecom_alert("\n".join(msg_lines))
    
    else:
        print("\n  ✓ 数据新鲜度正常，无需修复")
    
    # 4. 记录检查结果
    result = {
        "check_time": datetime.now().isoformat(),
        "today": today.isoformat(),
        "latest_date_in_data": latest_date.isoformat() if latest_date else None,
        "stale_count": len(stale_files),
        "stale_files": [{"file": f, "last_date": d.isoformat() if d else None} for f, d in stale_files],
        "need_fix": need_fix,
        "check_only": args.check_only,
    }
    
    output_file = PM_DATA_DIR / f"{today.isoformat()}-freshness.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n  📝 检查结果已保存: {output_file}")
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 数据新鲜度检查完成")
    
    return 0 if not stale_files else 1


if __name__ == "__main__":
    sys.exit(main())
