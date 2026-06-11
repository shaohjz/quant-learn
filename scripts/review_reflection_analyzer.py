"""Analyze manually filled review reflection notes (REQ-015).

This tool scans ``docs/reviews/*.md`` for manually filled sections such as
``思考问题`` / ``复盘要点`` / ``反思`` and writes structured analysis + action
items back into the local system database.  It is intentionally deterministic
and idempotent so it can be run by a daily scheduled task without requiring an
LLM service.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEWS_DIR = ROOT / "docs" / "reviews"
DEFAULT_DB_PATH = ROOT / "data" / "sim_live_mirror.db"

SECTION_TRIGGERS = ("思考问题", "复盘要点", "反思", "手工", "行动项", "改进")
PLACEHOLDER_PATTERNS = (
    "在此填写",
    "待填写",
    "暂无",
    "无",
    "todo",
    "tbd",
    "xxx",
    "（",
)
CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("risk_control", ("风控", "止损", "回撤", "仓位", "亏损", "风险", "追高", "跌破")),
    ("trade_execution", ("成交", "下单", "卖", "买", "执行", "QMT", "broker", "挂单", "撤单")),
    ("strategy_review", ("信号", "策略", "模型", "阈值", "选股", "买入区", "卖出区", "趋势")),
    ("data_quality", ("数据", "漏", "缺失", "同步", "口径", "对账", "回填", "记录")),
    ("process_improvement", ("流程", "提醒", "复盘", "纪律", "计划", "检查", "每日")),
)
HIGH_PRIORITY_WORDS = ("严重", "必须", "立即", "禁止", "失控", "大亏", "漏卖", "漏单", "异常")
MEDIUM_PRIORITY_WORDS = ("应该", "需要", "建议", "尽快", "改进", "跟进", "复核", "检查")


@dataclass(frozen=True)
class ReflectionItem:
    date: str
    source_file: str
    question: str
    answer: str
    raw_text: str
    content_hash: str


@dataclass(frozen=True)
class ReflectionAnalysis:
    date: str
    source_file: str
    question: str
    answer: str
    category: str
    priority: str
    action_item: str
    content_hash: str


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _date_from_path(path: Path) -> str | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    return match.group(1) if match else None


def _is_placeholder(text: str) -> bool:
    cleaned = re.sub(r"[\s\-\[\]xX:：。,.，?？]+", "", text).lower()
    if not cleaned:
        return True
    return any(p.lower() in cleaned for p in PLACEHOLDER_PATTERNS)


def _hash_item(date: str, source_file: str, question: str, answer: str) -> str:
    payload = "\n".join([date, source_file, question.strip(), answer.strip()])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _heading_level(line: str) -> int | None:
    match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
    return len(match.group(1)) if match else None


def _heading_title(line: str) -> str:
    return re.sub(r"^#{1,6}\s+", "", line).strip()


def _iter_trigger_sections(markdown: str) -> Iterable[tuple[str, str]]:
    """Yield (section_title, section_body) for relevant markdown sections."""
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        level = _heading_level(line)
        title = _heading_title(line) if level else ""
        if level and any(trigger in title for trigger in SECTION_TRIGGERS):
            body: list[str] = []
            i += 1
            while i < len(lines):
                next_level = _heading_level(lines[i])
                if next_level is not None and next_level <= level:
                    break
                body.append(lines[i])
                i += 1
            yield title, "\n".join(body).strip()
            continue
        i += 1

    # Some reports use bold inline labels instead of headings.
    for match in re.finditer(
        r"(?:^|\n)\*\*(?P<title>[^*]*(?:思考问题|复盘要点|反思|手工|行动项|改进)[^*]*)\*\*\s*[:：]?\s*\n(?P<body>.*?)(?=\n\s*\n(?:#{1,6}\s+|\*\*[^*]+\*\*)|\n#{1,6}\s+|\Z)",
        markdown,
        flags=re.DOTALL,
    ):
        yield match.group("title").strip(), match.group("body").strip()


def _strip_checkbox_prefix(line: str) -> str:
    return re.sub(r"^\s*[-*+]\s*\[[ xX]\]\s*", "", line).strip()


def _split_question_answer(text: str, fallback_question: str) -> tuple[str, str]:
    text = text.strip().strip("-• ").strip()
    text = _strip_checkbox_prefix(text)
    separators = (" -> ", "=>", "：", ":", "？", "?")
    for sep in separators:
        if sep in text:
            left, right = text.split(sep, 1)
            if right.strip():
                question = (left + sep.strip()).strip() if sep in ("？", "?") else left.strip()
                return question or fallback_question, right.strip()
    return fallback_question, text


def _extract_items_from_section(date: str, path: Path, title: str, body: str) -> list[ReflectionItem]:
    items: list[ReflectionItem] = []

    # Checklist / bullet lines are the most common format for manually filled
    # answers under 思考问题.
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or not re.match(r"^[-*+]\s*(?:\[[ xX]\]\s*)?", stripped):
            continue
        question, answer = _split_question_answer(stripped, title)
        if _is_placeholder(answer):
            continue
        content_hash = _hash_item(date, path.name, question, answer)
        items.append(ReflectionItem(date, path.name, question, answer, stripped, content_hash))

    # Paragraph fallback: keep manually written free-form content if the section
    # does not contain extractable bullets.
    if not items:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        for paragraph in paragraphs:
            compact = re.sub(r"\s+", " ", paragraph).strip()
            if _is_placeholder(compact):
                continue
            question, answer = _split_question_answer(compact, title)
            content_hash = _hash_item(date, path.name, question, answer)
            items.append(ReflectionItem(date, path.name, question, answer, compact, content_hash))

    return items


def extract_reflection_items(reviews_dir: Path = DEFAULT_REVIEWS_DIR) -> list[ReflectionItem]:
    """Extract manually filled review reflection items from markdown reports."""
    if not reviews_dir.exists():
        return []

    extracted: list[ReflectionItem] = []
    seen_hashes: set[str] = set()
    for path in sorted(reviews_dir.glob("*.md")):
        date = _date_from_path(path)
        if not date:
            continue
        markdown = _read_text(path)
        for title, body in _iter_trigger_sections(markdown):
            for item in _extract_items_from_section(date, path, title, body):
                if item.content_hash in seen_hashes:
                    continue
                seen_hashes.add(item.content_hash)
                extracted.append(item)
    return extracted


def classify_reflection(text: str) -> str:
    lowered = text.lower()
    for category, keywords in CATEGORY_RULES:
        if any(keyword.lower() in lowered for keyword in keywords):
            return category
    return "general"


def priority_for_reflection(text: str) -> str:
    lowered = text.lower()
    if any(word.lower() in lowered for word in HIGH_PRIORITY_WORDS):
        return "P1"
    if any(word.lower() in lowered for word in MEDIUM_PRIORITY_WORDS):
        return "P2"
    return "P3"


def build_action_item(item: ReflectionItem, category: str) -> str:
    answer = re.sub(r"\s+", " ", item.answer).strip()
    if len(answer) > 90:
        answer = answer[:87] + "..."
    templates = {
        "risk_control": "复核风控/仓位规则并补充可执行约束：{answer}",
        "trade_execution": "核对交易执行链路并记录处理结论：{answer}",
        "strategy_review": "回测或复核相关策略信号，形成参数/规则调整建议：{answer}",
        "data_quality": "检查数据同步与对账口径，必要时补齐缺失记录：{answer}",
        "process_improvement": "把复盘结论转成下个交易日检查清单：{answer}",
        "general": "跟进复盘结论并在下一次复盘验证：{answer}",
    }
    return templates.get(category, templates["general"]).format(answer=answer)


def analyze_items(items: Iterable[ReflectionItem]) -> list[ReflectionAnalysis]:
    analyses: list[ReflectionAnalysis] = []
    for item in items:
        full_text = f"{item.question}\n{item.answer}"
        category = classify_reflection(full_text)
        analyses.append(
            ReflectionAnalysis(
                date=item.date,
                source_file=item.source_file,
                question=item.question,
                answer=item.answer,
                category=category,
                priority=priority_for_reflection(full_text),
                action_item=build_action_item(item, category),
                content_hash=item.content_hash,
            )
        )
    return analyses


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_reflection_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            source_file TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            category TEXT NOT NULL,
            priority TEXT NOT NULL,
            action_item TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            content_hash TEXT NOT NULL UNIQUE,
            analyzed_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_reflection_analysis_date "
        "ON review_reflection_analysis(date)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_reflection_analysis_status "
        "ON review_reflection_analysis(status, priority)"
    )


def save_analyses(analyses: Iterable[ReflectionAnalysis], db_path: Path = DEFAULT_DB_PATH) -> int:
    """Persist analyses and return number of rows inserted/updated."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(analyses)
    now = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        for row in rows:
            conn.execute(
                """
                INSERT INTO review_reflection_analysis (
                    date, source_file, question, answer, category, priority,
                    action_item, status, content_hash, analyzed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
                ON CONFLICT(content_hash) DO UPDATE SET
                    question=excluded.question,
                    answer=excluded.answer,
                    category=excluded.category,
                    priority=excluded.priority,
                    action_item=excluded.action_item,
                    analyzed_at=excluded.analyzed_at
                """,
                (
                    row.date,
                    row.source_file,
                    row.question,
                    row.answer,
                    row.category,
                    row.priority,
                    row.action_item,
                    row.content_hash,
                    now,
                ),
            )
        conn.commit()
    return len(rows)


def analyze_reviews(reviews_dir: Path = DEFAULT_REVIEWS_DIR,
                    db_path: Path = DEFAULT_DB_PATH,
                    dry_run: bool = False) -> list[ReflectionAnalysis]:
    items = extract_reflection_items(reviews_dir)
    analyses = analyze_items(items)
    if not dry_run:
        save_analyses(analyses, db_path)
    return analyses


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze manually filled daily review reflections")
    parser.add_argument("--reviews-dir", default=str(DEFAULT_REVIEWS_DIR))
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", help="print JSON rows")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    analyses = analyze_reviews(Path(args.reviews_dir), Path(args.db), dry_run=args.dry_run)
    if args.json:
        print(json.dumps([asdict(row) for row in analyses], ensure_ascii=False, indent=2))
    else:
        action = "would analyze" if args.dry_run else "analyzed"
        print(f"{action} {len(analyses)} review reflection item(s)")
        for row in analyses:
            print(f"- {row.date} [{row.priority}/{row.category}] {row.action_item}")


if __name__ == "__main__":
    main()
