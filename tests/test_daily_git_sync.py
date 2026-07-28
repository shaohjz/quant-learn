"""daily_git_sync 白名单与摘要文案。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "daily_git_sync", ROOT / "scripts" / "daily_git_sync.py"
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_allow_trade_journal_and_daily_close():
    assert mod._is_allowed("pm/trade_journal/2026-07-20.md")
    assert mod._is_allowed("pm/trade_journal/2026-07-20.json")
    assert mod._is_allowed("output/daily_close_2026-07-20.md")
    assert mod._is_allowed("output/swing_daily/2026-07-20.md")
    assert mod._is_allowed("daily_reports/2026-07-20-rd-report.md")
    assert mod._is_allowed("output/finance_manager/x.md")
    assert mod._is_allowed("output/pm_daily_report_2026-07-20.md")
    assert mod._is_allowed("pm/archive/REQ-001.md")
    assert mod._is_allowed("pm/BACKLOG.md")
    assert not mod._is_allowed("scripts/trade_journal.py")
    assert not mod._is_allowed("data/sim_live_mirror.db")
    assert not mod._is_allowed("config.local.yaml")


def test_summary_md_mentions_status():
    text = mod._summary_md(
        "2026-07-20",
        "上报成功",
        [
            "pm/trade_journal/2026-07-20.md",
            "output/daily_close_2026-07-20.md",
            "pm/ops/2026-07-20-deploy.md",
        ],
        remote="origin",
        branch="master",
        remote_url="git@git.woa.com:jizhouhu/quant-learn.git",
        commit="abc1234",
    )
    assert "上报成功" in text
    assert "origin/master" in text
    assert "git@git.woa.com:jizhouhu/quant-learn.git" in text
    assert "abc1234" in text
    assert "交易台账: 1" in text
    assert "日总结: 1" in text
    assert "pm/trade_journal/2026-07-20.md" in text


def test_path_stats():
    s = mod._path_stats(
        [
            "pm/trade_journal/a.md",
            "output/daily_close_2026-07-20.md",
            "daily_reports/2026-07-20-rd-report.md",
            "output/swing_daily/x.md",
            "pm/bugs/BUG-1.md",
        ]
    )
    assert s["交易台账"] == 1
    assert s["日总结"] == 2
    assert s["波段日报/池"] == 1
    assert s["PM/队列/BUG"] == 1
