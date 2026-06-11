from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.portfolio_alert as portfolio_alert


def test_portfolio_alert_after_hours_exits_silently(monkeypatch, capsys, tmp_path):
    """BUG-015: non-trading cron wakeups must not spam runner/log files."""
    log_file = tmp_path / "portfolio_alert.log"
    monkeypatch.setenv("PORTFOLIO_ALERT_NOW", "2026-06-01T17:21:00")
    monkeypatch.setattr(portfolio_alert, "LOG_FILE", log_file)
    monkeypatch.setattr(portfolio_alert, "RULES", None)

    def fail_if_loaded():  # proves the early guard runs before rule/config loading
        raise AssertionError("rules should not be loaded outside trading hours")

    monkeypatch.setattr(portfolio_alert, "load_all_alert_rules", fail_if_loaded)

    assert portfolio_alert.main() == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert not log_file.exists()
