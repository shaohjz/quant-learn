from pathlib import Path

from broker.base import Account, Position
from scripts import daily_review_vnpy as drv


def _write_qmt_config(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.local.yaml").write_text(
        """
broker:
  live:
    qmt_account: "90072426"
    qmt_path: 'D:\\国金QMT交易端模拟\\userdata_mini'
    session_id: 970515
    dry_run: true
    xtquant_site_packages: 'D:\\国金QMT交易端模拟\\bin.x64\\Lib\\site-packages'
""".strip(),
        encoding="utf-8",
    )


def test_bug007_qmt_snapshot_uses_real_readonly_connection_not_dry_run_fake(tmp_path, monkeypatch):
    """QMT 复盘查询必须真实只读连接；不能用 dry_run 伪造 1000 万空仓。"""
    _write_qmt_config(tmp_path)
    monkeypatch.setattr(drv, "ROOT", tmp_path)

    calls = []

    class FakeBroker:
        def get_account(self):
            return Account(cash=900.0, market_value=100.0, total_value=1000.0, initial_cash=0.0)

        def get_positions(self):
            return [
                Position(
                    stock_code="000001",
                    stock_name="平安银行",
                    quantity=100,
                    avg_cost=10.0,
                    current_price=11.0,
                    market_value=1100.0,
                    pnl=100.0,
                    pnl_pct=10.0,
                )
            ]

        def disconnect(self):
            pass

    def fake_get_broker(mode, **kwargs):
        calls.append((mode, kwargs))
        return FakeBroker()

    import broker.factory as factory

    monkeypatch.setattr(factory, "get_broker", fake_get_broker)

    snap = drv.fetch_qmt_snapshot("2026-05-26", allow_qmt=True)

    assert calls, "expected QMT broker to be created"
    assert calls[0][0] == "qmt"
    assert calls[0][1]["dry_run"] is False
    assert snap["source"] == "qmt_live"
    assert snap["account"]["total_value"] == 1000.0
    assert snap["positions"][0]["stock_code"] == "000001"


def test_bug007_qmt_snapshot_failure_is_unavailable_not_10m_fake(tmp_path, monkeypatch):
    """连接失败时应明确 unavailable，不再返回 dry-run 1000 万空仓伪账户。"""
    _write_qmt_config(tmp_path)
    monkeypatch.setattr(drv, "ROOT", tmp_path)

    def fake_get_broker(mode, **kwargs):
        raise RuntimeError("QMT client not running")

    import broker.factory as factory

    monkeypatch.setattr(factory, "get_broker", fake_get_broker)

    snap = drv.fetch_qmt_snapshot("2026-05-26", allow_qmt=True)

    assert snap["source"] == "unavailable"
    assert snap["account"] is None
    assert snap["positions"] == []
    assert "dry-run" in snap["note"] or "伪账户" in snap["note"]
