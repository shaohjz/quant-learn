"""scripts/strategy_scorecard.py — 每日策略记分卡

把信号台账变成一句能回答「策略在变好还是变坏」的结论，并落盘成时间序列。

在此之前，每日"反馈"只是 LLM 写的散文日报：读起来像复盘，但没有任何数字沉淀，
所以昨天和上个月的策略表现无法比较，也没人能发现某类信号已经悄悄转负。

产出：
  output/strategy_scorecard/YYYY-MM-DD.json   机器读（周度复盘与自动调参的输入）
  output/strategy_scorecard/YYYY-MM-DD.md     人读
  output/strategy_scorecard/latest.json       最近一份

只读 signal_outcomes；不改参数、不下单。默认推一条企微短讯。

用法：
  python scripts/strategy_scorecard.py
  python scripts/strategy_scorecard.py --no-push
  python scripts/strategy_scorecard.py --date 2026-07-30 --windows 20,60
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from research.strategy_scorecard import build_scorecard, render_markdown  # noqa: E402
from sim.config_resolver import resolve_artifact_root, resolve_db_path  # noqa: E402
from sim.signal_ledger import fetch_outcomes  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("scorecard")

ALARM_ICON = {"critical": "🚨", "warn": "⚠️", "info": "💡"}


def build_wecom_message(card: dict) -> str:
    """企微短讯：一行结论 + 最多 3 条告警。刻意不贴大表，长文看仓库文件。"""
    lines = [
        f"## 📊 策略记分卡 {card['as_of']}",
        "",
        f"**{card.get('verdict', '')}**",
    ]
    alarms = card.get("alarms") or []
    if alarms:
        lines.append("")
        for a in alarms[:3]:
            lines.append(f"{ALARM_ICON.get(a['level'], '·')} {a['message']}")
        if len(alarms) > 3:
            lines.append(f"> 另有 {len(alarms) - 3} 条，见 output/strategy_scorecard/")
    lines += ["", f"> 明细：output/strategy_scorecard/{card['as_of']}.md"]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="每日策略记分卡（只读）")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--db", default=None)
    ap.add_argument("--windows", default="20,60", help="滚动窗口（有信号的交易日个数）")
    ap.add_argument("--min-samples", type=int, default=None, help="出告警的最小样本量")
    ap.add_argument("--no-push", action="store_true", help="不推企微")
    args = ap.parse_args()

    windows = tuple(int(w) for w in args.windows.split(",") if w.strip())

    min_samples = args.min_samples
    if min_samples is None:
        try:
            from sim.config import get as cfg_get

            min_samples = int(cfg_get("strategy_feedback.scorecard.min_samples_for_alarm", 20))
        except Exception:
            min_samples = 20

    db_path = resolve_db_path(args.db)
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        rows = fetch_outcomes(conn)
    finally:
        conn.close()

    card = build_scorecard(rows, as_of=args.date, windows=windows, min_samples=min_samples)
    log.info("台账 %d 条；结论：%s", len(rows), card.get("verdict"))

    out_dir = resolve_artifact_root() / "strategy_scorecard"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{args.date}.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / f"{args.date}.md").write_text(render_markdown(card), encoding="utf-8")
    (out_dir / "latest.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("已落盘 %s", out_dir / f"{args.date}.md")

    for alarm in card.get("alarms") or []:
        log.warning("[%s] %s", alarm["level"], alarm["message"])

    if not args.no_push:
        try:
            from wecom_webhook import push_markdown_safe

            push_markdown_safe(build_wecom_message(card))
        except Exception as exc:  # 推送失败不能让落盘白跑
            log.warning("企微推送失败：%s", exc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
