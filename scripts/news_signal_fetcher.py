"""
scripts/news_signal_fetcher.py — 新闻信号获取器

从 akshare 拉取持仓股+观察池的新闻，写入 strategy_shadow_signals 表。
纯数据层，不涉及 LLM 分析。LLM 在 cron 任务中读取后做利好/利空判断。

用法：
  python scripts/news_signal_fetcher.py              # 拉取所有观察股+持仓股新闻
  python scripts/news_signal_fetcher.py --code 600519  # 拉取指定股票新闻

写入 strategy_shadow_signals 表：
  strategy_id = 'news_sentiment'  # 新闻情绪信号
  signal_action = 'PENDING'       # 待 LLM 分析
  confidence = 0.0                # 待 LLM 赋值
"""

import sys, json, os
from pathlib import Path
from datetime import datetime
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sqlite3
import akshare as ak
import pandas as pd

DB_PATH = ROOT / "data" / "sim_live_mirror.db"
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# 观察池股票代码
WATCH_CODES = [
    "000600", "000899", "002067", "002149", "002290", "002312", "002340",
    "002371", "002463", "002475", "002594", "002600", "002625", "002916",
    "300059", "300124", "300274", "300308", "300433", "300502", "300750",
    "300760", "600036", "600150", "600519", "600690", "600941", "601138",
    "601899", "603160", "603259", "603501", "603986", "603993", "688008",
    "688041", "688072", "688111", "688256", "688525", "688981",
]


def get_stock_name(code: str) -> str:
    """从 DB 获取股票名称"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        c.execute("SELECT stock_name FROM watchlist_history WHERE stock_code=? LIMIT 1", (code,))
        r = c.fetchone()
        conn.close()
        if r:
            return r[0]
    except Exception:
        pass
    return code


def write_signal(stock_code: str, stock_name: str, news_title: str, news_content: str,
                 news_time: str, news_source: str, news_url: str) -> bool:
    """写入 strategy_shadow_signals 表，返回是否新增"""
    now = datetime.now()
    shadow_date = now.strftime("%Y-%m-%d")
    shadow_time = now.strftime("%H:%M:%S")
    created_at = now.strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(str(DB_PATH))
    try:
        c = conn.cursor()
        # 去重：同股票+同标题+同日期
        c.execute("""
            SELECT id FROM strategy_shadow_signals 
            WHERE strategy_id='news_sentiment' AND stock_code=? AND signal_reason LIKE ? 
            AND shadow_date=?
        """, (stock_code, f"{news_title[:100]}%", shadow_date))
        if c.fetchone():
            return False

        # 构建 signal_reason: 标题|来源|时间|内容摘要
        reason = f"{news_title[:200]}|{news_source}|{news_time}|{news_content[:200]}"

        c.execute("""
            INSERT INTO strategy_shadow_signals 
            (shadow_date, shadow_time, strategy_id, stock_code, stock_name,
             price, position, signal_action, signal_rule, signal_reason, confidence, created_at)
            VALUES (?, ?, 'news_sentiment', ?, ?,
                    0, 0, 'PENDING', 'news_pending', ?, 0.0, ?)
        """, (shadow_date, shadow_time, stock_code, stock_name, reason, created_at))
        conn.commit()
        return True
    except Exception as e:
        print(f"  ❌ 写入失败 {stock_code}: {e}")
        return False
    finally:
        conn.close()


def fetch_all_news(codes: list[str] = None, max_news_per_code: int = 5):
    """拉取多只股票的新闻并写入 DB"""
    if codes is None:
        codes = WATCH_CODES

    total_written = 0
    total_skipped = 0
    errors = []

    for i, code in enumerate(codes):
        name = get_stock_name(code)
        print(f"[{i+1}/{len(codes)}] {code}({name})...", end=" ", flush=True)
        try:
            df = ak.stock_news_em(code)
            if df is None or len(df) == 0:
                print("无新闻")
                continue

            # 取最近 max_news_per_code 条
            df = df.head(max_news_per_code)
            written = 0
            for _, row in df.iterrows():
                title = str(row.get("新闻标题", ""))
                content = str(row.get("新闻内容", ""))
                news_time = str(row.get("发布时间", ""))
                source = str(row.get("文章来源", ""))
                url = str(row.get("新闻链接", ""))
                if write_signal(code, name, title, content, news_time, source, url):
                    written += 1
            total_written += written
            total_skipped += len(df) - written
            print(f"{written}条新 / {len(df)-written}条重复")
        except Exception as e:
            print(f"❌ 错误: {e}")
            errors.append(f"{code}: {e}")

    print(f"\n✅ 完成！新增 {total_written} 条，跳过 {total_skipped} 条重复")
    if errors:
        print(f"⚠️ 错误: {'; '.join(errors)}")

    # 导出待分析信号到 JSON
    save_pending_signals()

    return total_written


def save_pending_signals():
    """将今日待分析的新闻信号导出为 JSON"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("""
            SELECT id, stock_code, stock_name, signal_reason, shadow_time
            FROM strategy_shadow_signals
            WHERE strategy_id='news_sentiment' AND signal_action='PENDING'
            AND shadow_date=?
            ORDER BY shadow_time DESC
        """, (today,))
        rows = c.fetchall()

        signals = []
        for r in rows:
            parts = (r[3] or "").split("|")
            title = parts[0] if len(parts) > 0 else ""
            source = parts[1] if len(parts) > 1 else ""
            news_time = parts[2] if len(parts) > 2 else ""
            signals.append({
                "id": r[0],
                "stock_code": r[1],
                "stock_name": r[2],
                "title": title,
                "source": source,
                "news_time": news_time,
                "shadow_time": r[4],
            })

        out_path = OUTPUT_DIR / f"news_signals_{today}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"date": today, "total": len(signals), "signals": signals},
                     f, ensure_ascii=False, indent=2)
        print(f"\n📄 已导出 {len(signals)} 条待分析信号到 {out_path}")
    finally:
        conn.close()


def update_signal_llm(signal_id: int, action: str, confidence: float, reason: str):
    """LLM 分析后更新信号（供 cron 任务调用）"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        c = conn.cursor()
        c.execute("""
            UPDATE strategy_shadow_signals 
            SET signal_action=?, confidence=?, signal_reason=?
            WHERE id=?
        """, (action, confidence, reason, signal_id))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def get_pending_signals_for_llm() -> list[dict]:
    """获取今日待 LLM 分析的信号（供 cron 任务调用）"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("""
            SELECT id, stock_code, stock_name, signal_reason, shadow_time
            FROM strategy_shadow_signals
            WHERE strategy_id='news_sentiment' AND signal_action='PENDING'
            AND shadow_date=?
            ORDER BY stock_code, shadow_time
        """, (today,))
        signals = []
        for r in c.fetchall():
            parts = (r[3] or "").split("|")
            title = parts[0] if len(parts) > 0 else ""
            source = parts[1] if len(parts) > 1 else ""
            news_time = parts[2] if len(parts) > 2 else ""
            summary = parts[3] if len(parts) > 3 else ""
            signals.append({
                "id": r[0],
                "stock_code": r[1],
                "stock_name": r[2],
                "title": title,
                "source": source,
                "news_time": news_time,
                "summary": summary,
            })
        return signals
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="新闻信号获取器")
    parser.add_argument("--code", type=str, help="指定股票代码")
    parser.add_argument("--max-news", type=int, default=5, help="每只股票最多拉取新闻数")
    args = parser.parse_args()

    if args.code:
        fetch_all_news([args.code], max_news_per_code=args.max_news)
    else:
        fetch_all_news(max_news_per_code=args.max_news)
