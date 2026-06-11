from pathlib import Path

from scripts.daily_review_vnpy import render_markdown


def _split_markdown_row(row: str) -> list[str]:
    """Split a markdown row on unescaped pipes only."""
    assert row.startswith("|") and row.endswith("|")
    cells: list[str] = []
    buf: list[str] = []
    escaped = False
    for ch in row[1:-1]:
        if ch == "|" and not escaped:
            cells.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
        escaped = (ch == "\\") and not escaped
        if ch != "\\":
            escaped = False
    cells.append("".join(buf).strip())
    return cells


def test_trade_table_escapes_signal_reason_pipe_and_keeps_broker_column(tmp_path: Path):
    sim_snap = {
        "db_path": "sim_live_mirror.db",
        "account": {
            "initial_cash": 25000,
            "cash": 10000,
            "total_value": 26000,
        },
        "positions": [],
        "trades": [
            {
                "trade_date": "2026-05-26",
                "stock_code": "002709",
                "stock_name": "天赐材料",
                "direction": "BUY",
                "quantity": 100,
                "price": 51.96,
                "amount": 5196,
                "signal_reason": "自动: buy_zone | 💰 天赐材料跌至买入区",
                "broker": "live_mirror",
            }
        ],
    }
    qmt_snap = {"source": "qmt_live", "account": None, "positions": [], "trades": []}

    md = render_markdown("2026-05-26", sim_snap, qmt_snap, reports_dir=tmp_path)
    row = next(line for line in md.splitlines() if line.startswith("| 2026-05-26 |"))
    cells = _split_markdown_row(row)

    assert len(cells) == 8
    assert cells[6] == r"自动: buy_zone \| 💰 天赐材料跌至买入区"
    assert cells[7] == "live_mirror"
