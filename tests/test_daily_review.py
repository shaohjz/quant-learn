"""tests/test_daily_review.py — Phase 2 daily_review_vnpy 测试

不真连 QMT，只验证：
  1) sim 数据从 sim_live_mirror.db 正确加载
  2) markdown 生成结构合法
  3) FORBIDDEN_ACCOUNTS 闸门生效
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_assert_safe_blocks_real_account():
    from scripts.daily_review_vnpy import _assert_safe
    try:
        _assert_safe("8890461376")
    except RuntimeError as e:
        assert "禁止访问真实账户" in str(e)
        print(f"✅ FORBIDDEN_ACCOUNTS 闸门生效: {e}")
        return
    raise AssertionError("应该抛 RuntimeError")


def test_fetch_sim_snapshot_from_mirror():
    from scripts.daily_review_vnpy import fetch_sim_snapshot
    p = ROOT / "data" / "sim_live_mirror.db"
    if not p.exists():
        print(f"⚠️ {p} 不存在，跳过")
        return
    snap = fetch_sim_snapshot("2026-05-19", p)
    assert snap["account"], f"账户加载失败: {snap}"
    # 5/22 双账户重构：live_mirror 已重置为 100,000；这里只校验 fetch 拿到合法账户
    assert snap["account"]["initial_cash"] in (25000.0, 100000.0), snap["account"]
    assert snap["account"]["name"] in ("sim", "live_mirror", "default"), snap["account"]
    assert len(snap["positions"]) >= 1, "至少 1 个持仓"
    print(f"✅ sim_live_mirror 解析 OK: {len(snap['positions'])} 仓 / {len(snap['trades'])} 笔")


def test_render_markdown_runnable():
    from scripts.daily_review_vnpy import render_markdown
    sim = {
        "account": {"name": "sim", "initial_cash": 25000, "cash": 2500, "total_value": 23000},
        "positions": [{"stock_code": "600330", "stock_name": "天通", "quantity": 400,
                       "avg_cost": 32.0, "current_price": 30.0, "market_value": 12000,
                       "pnl": -800, "pnl_pct": -6.25}],
        "trades": [],
        "db_path": "fake.db",
    }
    qmt = {"source": "unavailable", "account": None, "positions": [], "trades": []}
    md = render_markdown("2026-05-19", sim, qmt)
    assert "# 双账户复盘 2026-05-19" in md
    assert "600330" in md
    assert "QMT mini" in md
    print(f"✅ markdown 生成 OK ({len(md)} chars)")


if __name__ == "__main__":
    test_assert_safe_blocks_real_account()
    test_fetch_sim_snapshot_from_mirror()
    test_render_markdown_runnable()
    print("\n🎉 Phase 2 tests passed")
