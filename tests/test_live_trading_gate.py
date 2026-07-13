"""
tests/test_live_trading_gate.py — QL-000 自动交易总闸测试

覆盖四类场景：
1. 配置缺失（live_enabled 未设置或为 false）
2. 令牌错误（环境变量与配置不匹配）
3. 账户不在白名单
4. 金额超限（单笔/单日）
"""

import os
import pytest
from datetime import date as Date
from unittest.mock import patch

from broker.trading_gate import LiveTradingGate, GateDecision, check_live_order


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _make_config(**overrides) -> dict:
    """生成测试配置，默认 sim 模式安全"""
    base = {
        "broker": {"mode": "sim"},
        "accounts": {
            "learn": {
                "account_id": 1,
                "account_name": "learn",
                "initial_cash": 200000.0,
                "max_total_value": 200000.0,
            }
        },
        "risk": {
            "max_daily_build_amount_pct": 0.30,
            "stop_loss_pct": -0.08,
        },
    }
    trading = overrides.pop("trading", None)
    if trading:
        base["trading"] = trading
    base.update(overrides)
    return base


# ------------------------------------------------------------------
# Test: sim / dry_run 模式永远允许
# ------------------------------------------------------------------
class TestSimPassThrough:
    """sim 和 dry_run 模式不受总闸限制"""

    def test_sim_mode_always_allowed(self):
        gate = LiveTradingGate(config=_make_config())
        result = gate.check(mode="sim", account_id="any", order_amount=999999.0)
        assert result.allowed is True
        assert "sim" in result.reason

    def test_dry_run_mode_always_allowed(self):
        gate = LiveTradingGate(config=_make_config())
        result = gate.check(mode="dry_run", account_id="any", order_amount=999999.0)
        assert result.allowed is True
        assert "dry_run" in result.reason

    def test_sim_mode_ignores_all_checks(self):
        """即使所有实盘检查条件都不满足，sim 模式仍然通过"""
        config = _make_config(trading={
            "live_enabled": False,
            # 不设置 live_token 和 allowed_accounts
        })
        gate = LiveTradingGate(config=config)
        result = gate.check(mode="sim", account_id="unknown", order_amount=999999.0)
        assert result.allowed is True


# ------------------------------------------------------------------
# Test 1: 配置缺失 / live_enabled 为 False
# ------------------------------------------------------------------
class TestConfigMissing:
    """live_enabled 未设置或为 False 时拒绝实盘"""

    def test_live_enabled_false_blocks_order(self):
        config = _make_config(trading={
            "live_enabled": False,
            "live_token": "test-token-123",
            "allowed_accounts": ["90072426"],
        })
        gate = LiveTradingGate(config=config)
        result = gate.check(mode="qmt", account_id="90072426", order_amount=100.0)
        assert result.allowed is False
        assert "live_enabled" in result.reason

    def test_no_trading_config_blocks_order(self):
        """完全没有 trading 配置节时拒绝"""
        config = _make_config()  # 没有 trading 节
        gate = LiveTradingGate(config=config)
        result = gate.check(mode="live", account_id="90072426", order_amount=100.0)
        assert result.allowed is False

    def test_live_enabled_true_with_other_checks_passing(self):
        """live_enabled=True + 其他条件满足时允许"""
        config = _make_config(trading={
            "live_enabled": True,
            "live_token": "test-token-123",
            "allowed_accounts": ["90072426"],
        })
        gate = LiveTradingGate(config=config)
        with patch.dict(os.environ, {"QUANT_LIVE_TOKEN": "test-token-123"}):
            result = gate.check(mode="qmt", account_id="90072426", order_amount=100.0)
            assert result.allowed is True


# ------------------------------------------------------------------
# Test 2: 令牌错误
# ------------------------------------------------------------------
class TestTokenMismatch:
    """环境变量令牌与配置不匹配时拒绝"""

    def test_token_mismatch_blocks_order(self):
        config = _make_config(trading={
            "live_enabled": True,
            "live_token": "correct-token",
            "allowed_accounts": ["90072426"],
        })
        gate = LiveTradingGate(config=config)
        with patch.dict(os.environ, {"QUANT_LIVE_TOKEN": "wrong-token"}):
            result = gate.check(mode="qmt", account_id="90072426", order_amount=100.0)
            assert result.allowed is False
            assert "mismatch" in result.reason.lower() or "token" in result.reason.lower()

    def test_token_env_missing_blocks_order(self):
        """QUANT_LIVE_TOKEN 环境变量不存在"""
        config = _make_config(trading={
            "live_enabled": True,
            "live_token": "some-token",
            "allowed_accounts": ["90072426"],
        })
        gate = LiveTradingGate(config=config)
        with patch.dict(os.environ, {}, clear=True):
            # clear=True 确保没有 QUANT_LIVE_TOKEN
            # 但可能清除其他必要环境变量，所以只删除这一个
            pass
        # 使用更精确的方式：确保 QUANT_LIVE_TOKEN 不存在
        env_copy = dict(os.environ)
        env_copy.pop("QUANT_LIVE_TOKEN", None)
        with patch.dict(os.environ, env_copy, clear=True):
            result = gate.check(mode="qmt", account_id="90072426", order_amount=100.0)
            assert result.allowed is False

    def test_no_token_configured_blocks_order(self):
        """trading.live_token 未配置"""
        config = _make_config(trading={
            "live_enabled": True,
            # live_token 缺失
            "allowed_accounts": ["90072426"],
        })
        gate = LiveTradingGate(config=config)
        result = gate.check(mode="qmt", account_id="90072426", order_amount=100.0)
        assert result.allowed is False
        assert "token" in result.reason.lower()


# ------------------------------------------------------------------
# Test 3: 账户不在白名单
# ------------------------------------------------------------------
class TestAccountWhitelist:
    """不在 allowlist 的账户永远不能真下单"""

    def test_unknown_account_blocked(self):
        config = _make_config(trading={
            "live_enabled": True,
            "live_token": "test-token",
            "allowed_accounts": ["90072426"],  # 只允许模拟账号
        })
        gate = LiveTradingGate(config=config)
        with patch.dict(os.environ, {"QUANT_LIVE_TOKEN": "test-token"}):
            result = gate.check(mode="qmt", account_id="8890461376", order_amount=100.0)
            assert result.allowed is False
            assert "whitelist" in result.reason.lower() or "allowed_accounts" in result.reason.lower()

    def test_empty_whitelist_blocks_all(self):
        """白名单为空时所有账户都被拒绝"""
        config = _make_config(trading={
            "live_enabled": True,
            "live_token": "test-token",
            "allowed_accounts": [],
        })
        gate = LiveTradingGate(config=config)
        with patch.dict(os.environ, {"QUANT_LIVE_TOKEN": "test-token"}):
            result = gate.check(mode="qmt", account_id="90072426", order_amount=100.0)
            assert result.allowed is False

    def test_no_whitelist_config_blocks_all(self):
        """没有 allowed_accounts 配置时拒绝所有实盘"""
        config = _make_config(trading={
            "live_enabled": True,
            "live_token": "test-token",
            # allowed_accounts 缺失
        })
        gate = LiveTradingGate(config=config)
        with patch.dict(os.environ, {"QUANT_LIVE_TOKEN": "test-token"}):
            result = gate.check(mode="qmt", account_id="90072426", order_amount=100.0)
            assert result.allowed is False


# ------------------------------------------------------------------
# Test 4: 金额超限
# ------------------------------------------------------------------
class TestAmountLimits:
    """单笔金额和当日累计金额超限时拒绝"""

    def _gate_with_all_checks_passing(self) -> LiveTradingGate:
        config = _make_config(trading={
            "live_enabled": True,
            "live_token": "test-token",
            "allowed_accounts": ["90072426"],
        })
        gate = LiveTradingGate(config=config)
        return gate

    def test_single_order_exceeds_limit(self):
        """单笔金额超过 max_total_value * max_daily_build_amount_pct"""
        gate = self._gate_with_all_checks_passing()
        # max_total_value=200000, max_daily_build_amount_pct=0.30 → 限额=60000
        with patch.dict(os.environ, {"QUANT_LIVE_TOKEN": "test-token"}):
            result = gate.check(mode="qmt", account_id="90072426", order_amount=70000.0)
            assert result.allowed is False
            assert "exceeds" in result.reason.lower() or "amount" in result.reason.lower()

    def test_daily_cumulative_exceeds_limit(self):
        """当日累计新建金额超限"""
        gate = self._gate_with_all_checks_passing()
        with patch.dict(os.environ, {"QUANT_LIVE_TOKEN": "test-token"}):
            # 先允许一笔 40000
            r1 = gate.check(mode="qmt", account_id="90072426", order_amount=40000.0)
            assert r1.allowed is True
            # 再一笔 30000 → 累计 70000 > 60000
            r2 = gate.check(mode="qmt", account_id="90072426", order_amount=30000.0)
            assert r2.allowed is False

    def test_normal_amount_passes(self):
        """正常金额通过"""
        gate = self._gate_with_all_checks_passing()
        with patch.dict(os.environ, {"QUANT_LIVE_TOKEN": "test-token"}):
            result = gate.check(mode="qmt", account_id="90072426", order_amount=10000.0)
            assert result.allowed is True

    def test_daily_reset_on_new_date(self):
        """新交易日重置当日累计"""
        gate = self._gate_with_all_checks_passing()
        with patch.dict(os.environ, {"QUANT_LIVE_TOKEN": "test-token"}):
            # Day 1: 允许一笔
            r1 = gate.check(mode="qmt", account_id="90072426", order_amount=40000.0,
                            trade_date=Date(2026, 7, 1))
            assert r1.allowed is True
            # Day 2: 累计已重置，允许同样金额
            r2 = gate.check(mode="qmt", account_id="90072426", order_amount=40000.0,
                            trade_date=Date(2026, 7, 2))
            assert r2.allowed is True


# ------------------------------------------------------------------
# Test: 便捷函数
# ------------------------------------------------------------------
class TestConvenienceFunction:
    def test_check_live_order_uses_default_gate(self):
        """check_live_order() 便捷函数正确工作"""
        result = check_live_order(mode="sim", account_id="any", order_amount=100.0)
        assert result.allowed is True


# ------------------------------------------------------------------
# Test: audit_log
# ------------------------------------------------------------------
class TestAuditLog:
    def test_audit_log_blocked(self):
        gate = LiveTradingGate(config=_make_config())
        decision = gate.check(mode="qmt", account_id="unknown", order_amount=100.0)
        # audit_log 不抛异常即可
        gate.audit_log(decision, stock_code="600330", side="BUY", quantity=100, price=30.0)


# ------------------------------------------------------------------
# Test: factory integration
# ------------------------------------------------------------------
class TestFactoryIntegration:
    """验证 broker/factory.py 在 live/qmt 模式下使用 TradingGate"""

    def test_factory_sim_mode_unchanged(self):
        """sim 模式行为不变 — 只验证 gate 检查通过，不真正创建 broker（避免 DB 依赖）"""
        from broker.trading_gate import check_live_order, LiveTradingGate
        # sim 模式不经过 TradingGate 限制
        decision = check_live_order(mode="sim", account_id="1", order_amount=100.0)
        assert decision.allowed is True

    def test_factory_qmt_blocked_by_gate(self):
        """QMT 模式被 TradingGate 拦截后不会创建真实 broker"""
        # 验证 TradingGate 在没有配置 trading 节时正确拦截
        from broker.trading_gate import LiveTradingGate
        gate = LiveTradingGate(config=_make_config())  # 没有 trading 节
        result = gate.check(mode="qmt", account_id="90072426", order_amount=100.0)
        assert result.allowed is False
        assert "live_enabled" in result.reason

    def test_factory_qmt_blocked_fallback_logic(self):
        """验证 factory.py 中 TradingGate 拦截后的回退逻辑（mock SimBroker）"""
        import broker.factory as factory_mod
        from broker.trading_gate import LiveTradingGate
        import broker.trading_gate as gate_mod

        # 重置单例以使用测试配置（没有 trading 节）
        gate_mod._default_gate = None
        gate_mod._default_gate = LiveTradingGate(config=_make_config())

        # Mock SimBroker 避免真实 DB 连接
        mock_broker = type("MockBroker", (), {
            "name": "sim",
            "connect": lambda self: True,
            "disconnect": lambda self: None,
        })()

        with patch.object(factory_mod, "SimBroker", return_value=mock_broker):
            with patch.dict(os.environ, {
                "QMT_USERDATA_MINI": "fake_path",
                "QMT_ACCOUNT_ID": "90072426",
            }):
                broker = factory_mod.get_broker(mode="qmt", account_id=1)
                assert broker.name == "sim"  # 回退到 sim

        # 清理单例
        gate_mod._default_gate = None
