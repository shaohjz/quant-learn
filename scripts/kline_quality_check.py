#!/usr/bin/env python3
"""K线数据质量监控脚本 - REQ-003

检查持仓股票的K线数据完整性：
1. 检测K线数据缺失（不足 20/60 根日K线）
2. 区分"数据缺失"和"停牌/未上市"
3. 输出需补全的标的列表
4. 生成 pm/data/YYYY-MM-DD-data.md 质量报告

用法:
    python scripts/kline_quality_check.py [--date YYYY-MM-DD] [--auto-backfill]
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "pm" / "data"
REPORT_DIR = PROJECT_ROOT / "output"

# 日志配置
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(REPORT_DIR / "kline_quality.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────

# 最少需要的K线数量
MIN_KLINE_SHORT = 20   # 短期均线（MA20）
MIN_KLINE_LONG  = 60    # 长期均线（MA60）
# 数据不足时触发告警的阈值
INSUFFICIENT_ALERT_DAYS = 30  # 少于30根日K线时告警

# 交易日历
TRADE_DATES: Optional[set] = None
trader_dates_path = DATA_DIR / "trade_dates.json"
if trader_dates_path.exists():
    try:
        with open(trader_dates_path, "r") as f:
            TRADE_DATES = set(json.load(f))
    except Exception:
        TRADE_DATES = None


def get_stock_list_from_positions() -> list[str]:
    """从 sim_live_mirror.db 的 position 表读取当前持仓股票代码"""
    try:
        import sqlite3
        db_path = DATA_DIR / "sim_live_mirror.db"
        if not db_path.exists():
            log.warning(f"DB 不存在: {db_path}")
            return []
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute("SELECT DISTINCT code FROM position WHERE volume > 0")
        codes = [row[0] for row in cur.fetchall()]
        conn.close()
        return codes
    except Exception as e:
        log.warning(f"读取持仓失败: {e}")
        return []


def get_all_stock_codes() -> list[str]:
    """获取 data/ 目录下所有 CSV 股票代码"""
    csv_files = sorted([f.stem for f in DATA_DIR.glob("*.csv") if f.stem.isdigit()])
    return csv_files


def load_kline_csv(symbol: str) -> Optional[pd.DataFrame]:
    """加载单只股票的K线CSV，返回 DataFrame"""
    csv_path = DATA_DIR / f"{symbol}.csv"
    if not csv_path.exists():
        return None
    try:
        df = pd.read_csv(csv_path, encoding="utf-8")
        if df.empty:
            return None
        # 统一列名
        col_map = {}
        for c in df.columns:
            cl = c.lower().strip()
            if cl in ("date", "日期"):
                col_map[c] = "date"
            elif cl in ("open", "开盘价"):
                col_map[c] = "open"
            elif cl in ("high", "最高价"):
                col_map[c] = "high"
            elif cl in ("low", "最低价"):
                col_map[c] = "low"
            elif cl in ("close", "收盘价"):
                col_map[c] = "close"
            elif cl in ("volume", "成交量"):
                col_map[c] = "volume"
        if col_map:
            df = df.rename(columns=col_map)
        # 确保 date 为 datetime
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df.sort_values("date")
        return df
    except Exception as e:
        log.warning(f"  加载 {symbol}.csv 失败: {e}")
        return None


def check_kline_sufficient(symbol: str, df: pd.DataFrame) -> dict:
    """检查单只股票K线数据是否充足，返回检查结果"""
    result = {
        "symbol": symbol,
        "status": "ok",
        "row_count": 0,
        "first_date": None,
        "last_date": None,
        "insufficient_ma20": False,
        "insufficient_ma60": False,
        "insufficient_reason": "",
        "possible_suspended": False,
        "need_backfill": False,
        "backfill_start": None,
        "backfill_end": None,
    }

    if df is None or df.empty:
        result["status"] = "missing"
        result["insufficient_reason"] = "CSV 文件不存在或为空"
        result["need_backfill"] = True
        result["backfill_start"] = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
        result["backfill_end"] = datetime.now().strftime("%Y-%m-%d")
        return result

    result["row_count"] = len(df)
    result["first_date"] = df["date"].iloc[0].strftime("%Y-%m-%d")
    result["last_date"] = df["date"].iloc[-1].strftime("%Y-%m-%d")

    # 检查数据时效性（最后日期距今多少天）
    last_dt = df["date"].iloc[-1]
    now = datetime.now()
    days_behind = (now - last_dt).days

    # 判断"数据缺失" vs "停牌/未上市"
    # 规则：如果最后日期在 30 天前，且期间有交易日缺失 → 数据缺失需补全
    #       如果 CSV 中日期连续（无跳空），但总量少 → 可能是新股/停牌
    if df is not None and not df.empty:
        date_series = df["date"].dt.date
        date_set = set(date_series)
        # 估算应有交易日数（最后120天）
        if TRADE_DATES:
            end_str = last_dt.strftime("%Y-%m-%d")
            start_dt = last_dt - timedelta(days=120)
            expected_trade_days = sum(
                1 for d in TRADE_DATES
                if start_dt.strftime("%Y-%m-%d") <= d <= end_str
            )
        else:
            # 粗略估算：120天 ≈ 80个交易日
            expected_trade_days = int(120 * 5 / 7)
        
        actual_count = result["row_count"]
        if actual_count < MIN_KLINE_SHORT:
            result["insufficient_ma20"] = True
            result["status"] = "insufficient"
            result["insufficient_reason"] = f"K线仅 {actual_count} 根，不足 MA20({MIN_KLINE_SHORT})"
            result["need_backfill"] = True
            result["backfill_start"] = (last_dt - timedelta(days=120)).strftime("%Y-%m-%d")
            result["backfill_end"] = datetime.now().strftime("%Y-%m-%d")

        if actual_count < MIN_KLINE_LONG:
            result["insufficient_ma60"] = True
            if not result["insufficient_reason"]:
                result["status"] = "insufficient"
                result["insufficient_reason"] = f"K线仅 {actual_count} 根，不足 MA60({MIN_KLINE_LONG})"
                result["need_backfill"] = True
                result["backfill_start"] = (last_dt - timedelta(days=200)).strftime("%Y-%m-%d")
                result["backfill_end"] = datetime.now().strftime("%Y-%m-%d")

        # 判断是否为停牌（数据连续但量少 = 新股；数据不连续 = 数据缺失）
        if actual_count >= 5:
            # 检查最近5个交易日的连续性
            recent = df.tail(20).copy()
            recent["date_diff"] = recent["date"].diff().dt.days
            max_gap = recent["date_diff"].max() if len(recent) > 1 else 0
            if max_gap and max_gap > 5:
                # 有跳空 → 数据缺失（需补全）
                result["possible_suspended"] = False
            else:
                # 无跳空，但总量少 → 可能是新股
                if actual_count < 30:
                    result["possible_suspended"] = "新股（数据量少但连续）"
        else:
            result["possible_suspended"] = "数据严重不足，无法判断"

    # 数据时效性检查
    if days_behind > 3:
        result["status"] = "outdated"
        result["need_backfill"] = True
        result["backfill_start"] = (last_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        result["backfill_end"] = datetime.now().strftime("%Y-%m-%d")

    return result


def run_backfill(symbols: list[str]) -> dict:
    """调用 backfill_data.py 补全指定股票的数据"""
    log.info(f"开始补数据: {len(symbols)} 只股票")
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "backfill_data.py")],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=600,
        )
        success = result.returncode == 0
        log.info(f"补数据完成: returncode={result.returncode}")
        if result.stdout:
            log.info(f"stdout: {result.stdout[-500:]}")
        if result.stderr:
            log.warning(f"stderr: {result.stderr[-500:]}")
        return {
            "success": success,
            "stdout": result.stdout[-1000:] if result.stdout else "",
            "stderr": result.stderr[-1000:] if result.stderr else "",
        }
    except Exception as e:
        log.error(f"补数据失败: {e}")
        return {"success": False, "error": str(e)}


def generate_quality_report(results: list[dict], date_str: str) -> str:
    """生成 pm/data/YYYY-MM-DD-data.md 质量报告"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"{date_str}-data.md"

    # 分类统计
    insufficient = [r for r in results if r["status"] in ("insufficient", "missing")]
    outdated = [r for r in results if r["status"] == "outdated"]
    ok = [r for r in results if r["status"] == "ok"]
    need_backfill = [r for r in results if r.get("need_backfill")]

    lines = []
    lines.append(f"# K线数据质量报告 {date_str}")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # 汇总
    lines.append("## 一、数据质量汇总")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 总股票数 | {len(results)} |")
    lines.append(f"| ✅ 正常 | {len(ok)} |")
    lines.append(f"| ⚠️ K线不足 | {len(insufficient)} |")
    lines.append(f"| ⏰ 数据过期 | {len(outdated)} |")
    lines.append(f"| 🔄 需补全 | {len(need_backfill)} |")
    lines.append("")

    # K线不足详情
    if insufficient:
        lines.append("## 二、K线数据不足标的")
        lines.append("")
        lines.append("| 代码 | 状态 | K线数量 | 原因 | 是否新股/停牌 | 需补全 |")
        lines.append("|------|------|----------|------|--------------|--------|")
        for r in insufficient:
            reason = r.get("insufficient_reason", "")[:40]
            suspended = r.get("possible_suspended", "-")
            if suspended is False:
                suspended = "-"
            need_bf = "✅" if r.get("need_backfill") else "❌"
            lines.append(f"| {r['symbol']} | {r['status']} | {r['row_count']} | {reason} | {suspended} | {need_bf} |")
        lines.append("")

    # 数据过期
    if outdated:
        lines.append("## 三、数据过期标的")
        lines.append("")
        lines.append("| 代码 | 最后日期 | 距今(天) |")
        lines.append("|------|----------|----------|")
        for r in outdated:
            last = r.get("last_date", "N/A")
            lines.append(f"| {r['symbol']} | {last} | N/A |")
        lines.append("")

    # 补全记录
    if need_backfill:
        lines.append("## 四、数据补全记录")
        lines.append("")
        lines.append(f"共 {len(need_backfill)} 只股票需要补全：")
        lines.append("")
        for r in need_backfill:
            start = r.get("backfill_start", "?")
            end = r.get("backfill_end", "?")
            lines.append(f"- `{r['symbol']}`: {start} ~ {end}")
        lines.append("")

    # 全部标的详情
    lines.append("## 五、全部标的详情")
    lines.append("")
    lines.append("| 代码 | 状态 | K线数 | 首日期 | 末日期 | MA20 | MA60 | 需补全 |")
    lines.append("|------|------|--------|--------|--------|------|------|--------|")
    for r in results:
        ma20 = "❌" if r.get("insufficient_ma20") else "✅"
        ma60 = "❌" if r.get("insufficient_ma60") else "✅"
        need_bf = "✅" if r.get("need_backfill") else "❌"
        lines.append(
            f"| {r['symbol']} | {r['status']} | {r['row_count']} | {r.get('first_date','?')} | {r.get('last_date','?')} | {ma20} | {ma60} | {need_bf} |"
        )
    lines.append("")

    # 行动项
    lines.append("## 六、行动项")
    lines.append("")
    action_items = []
    if insufficient:
        action_items.append(f"⚠️ **{len(insufficient)} 只股票 K线不足**，可能影响技术面破位监控和止损决策")
        action_items.append(f"   建议：运行 `python scripts/backfill_data.py` 补全数据")
    if need_backfill:
        action_items.append(f"🔄 **{len(need_backfill)} 只股票需要补全数据**")
    if not action_items:
        action_items.append("✅ 无紧急数据质量问题")

    for i, item in enumerate(action_items, 1):
        lines.append(f"{i}. {item}")
    lines.append("")
    lines.append("--- ")
    lines.append(f"*报告生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    lines.append("")

    report_content = "\n".join(lines)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    log.info(f"质量报告已生成: {report_path}")
    return str(report_path)


def send_notification(message: str):
    """发送企微通知（调用 notify.py）"""
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "notify.py"), "--msg", message],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            log.info("企微通知发送成功")
        else:
            log.warning(f"企微通知发送失败: {result.stderr[:200]}")
    except Exception as e:
        log.warning(f"发送通知失败: {e}")


def main():
    parser = argparse.ArgumentParser(description="K线数据质量监控")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="检查日期")
    parser.add_argument("--auto-backfill", action="store_true", help="自动补全缺失数据")
    parser.add_argument("--stocks", nargs="*", help="指定股票代码列表（默认：全部持仓+观察列表）")
    parser.add_argument("--all", action="store_true", help="检查 data/ 下所有CSV")
    args = parser.parse_args()

    date_str = args.date

    # 确定要检查的股票列表
    if args.stocks:
        stocks = args.stocks
    elif args.all:
        stocks = get_all_stock_codes()
    else:
        # 默认：持仓 + 观察列表
        stocks = get_stock_list_from_positions()
        if not stocks:
            log.warning("持仓为空，检查所有CSV")
            stocks = get_all_stock_codes()

    log.info(f"开始检查 {len(stocks)} 只股票的K线数据质量...")

    results = []
    for symbol in stocks:
        df = load_kline_csv(symbol)
        result = check_kline_sufficient(symbol, df)
        results.append(result)
        if result["status"] != "ok":
            log.info(f"  {symbol}: {result['status']} - {result.get('insufficient_reason', '')}")

    # 生成质量报告
    report_path = generate_quality_report(results, date_str)

    # 自动补全
    need_backfill = [r for r in results if r.get("need_backfill")]
    if args.auto_backfill and need_backfill:
        log.info(f"自动补全 {len(need_backfill)} 只股票的数据...")
        bf_result = run_backfill([r["symbol"] for r in need_backfill])
        # 补全后重新检查
        log.info("补全完成，重新检查...")
        results2 = []
        for symbol in [r["symbol"] for r in need_backfill]:
            df = load_kline_csv(symbol)
            results2.append(check_kline_sufficient(symbol, df))
        # 更新报告
        report_path = generate_quality_report(results + results2, date_str)

    # 数据不足时通知
    insufficient = [r for r in results if r["status"] in ("insufficient", "missing")]
    if insufficient:
        msg = f"⚠️ K线数据质量告警\n{len(insufficient)} 只股票K线不足，可能影响技术面分析。\n详情: {report_path}"
        log.warning(msg)
        send_notification(msg)

    # 输出 JSON 结果（供其他脚本调用）
    json_path = OUTPUT_DIR / f"{date_str}-data-check.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "check_time": datetime.now().isoformat(),
                "date": date_str,
                "summary": {
                    "total": len(results),
                    "ok": len([r for r in results if r["status"] == "ok"]),
                    "insufficient": len(insufficient),
                    "outdated": len([r for r in results if r["status"] == "outdated"]),
                    "need_backfill": len(need_backfill),
                },
                "details": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    log.info(f"JSON 结果已保存: {json_path}")

    # 返回状态码
    if insufficient:
        return 1  # 有数据不足
    return 0


if __name__ == "__main__":
    sys.exit(main())
