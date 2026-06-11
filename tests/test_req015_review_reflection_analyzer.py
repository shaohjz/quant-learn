from pathlib import Path
import sqlite3

from scripts.review_reflection_analyzer import (
    analyze_reviews,
    extract_reflection_items,
)


def test_extracts_manual_thinking_checklist_and_ignores_placeholders(tmp_path: Path):
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    (reviews / "2026-05-26.md").write_text(
        """# 双账户复盘 2026-05-26

## 思考问题
- [ ] 信号给出 SELL 但没卖的，事后看对不对？需要复核 broker 日志，疑似漏卖。
- [ ] 明天仓位怎么控？在此填写
- [x] 买入区是否过宽？建议把强买阈值调严，并回测最近 20 日。

## 备注
普通内容不应提取。
""",
        encoding="utf-8",
    )

    items = extract_reflection_items(reviews)

    assert len(items) == 2
    assert items[0].date == "2026-05-26"
    assert "SELL" in items[0].question
    assert "疑似漏卖" in items[0].answer
    assert "强买阈值" in items[1].answer


def test_analyze_reviews_persists_structured_action_items(tmp_path: Path):
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    db_path = tmp_path / "system.db"
    (reviews / "2026-05-27.md").write_text(
        """# 双账户复盘 2026-05-27

### 复盘要点
- [ ] 数据是否有缺失？需要检查 sim_trades 与 threshold_state 对账口径。
- [ ] 是否追高？必须降低单票仓位，避免回撤扩大。
""",
        encoding="utf-8",
    )

    analyses = analyze_reviews(reviews, db_path)

    assert len(analyses) == 2
    assert {a.category for a in analyses} == {"data_quality", "risk_control"}
    assert any(a.priority == "P1" for a in analyses)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "select date, category, priority, action_item, status from review_reflection_analysis order by id"
        ).fetchall()

    assert len(rows) == 2
    assert rows[0][0] == "2026-05-27"
    assert rows[0][1] == "data_quality"
    assert rows[0][4] == "open"
    assert "检查数据同步" in rows[0][3]

    # Idempotent rerun should not duplicate rows.
    analyze_reviews(reviews, db_path)
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("select count(*) from review_reflection_analysis").fetchone()[0]
    assert count == 2
