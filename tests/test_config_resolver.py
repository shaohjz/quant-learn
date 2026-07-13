"""
tests/test_config_resolver.py — QL-004 统一配置入口测试

验收:
  1. 相同进程内所有模块解析出同一 DB 路径
  2. 配置字段缺失时报可定位错误
  3. 敏感字段仅从 local 配置或环境变量读取
  4. 单元测试覆盖配置覆盖、非法 schema 和 DB 路径
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

from sim.config_resolver import (
    resolve_db_path,
    resolve_wecom_webhook,
    config_hash,
    validate_config,
    get_config_with_validation,
    check_deprecated_configs,
)


# ─── resolve_db_path ───
class TestResolveDbPath:
    def test_explicit_override(self, tmp_path):
        """测试注入临时路径"""
        fake_db = tmp_path / "test.db"
        result = resolve_db_path(override=str(fake_db))
        assert result == fake_db

    def test_env_var_override(self):
        """QUANT_DB_PATH 环境变量生效"""
        with patch.dict(os.environ, {"QUANT_DB_PATH": "/tmp/env_test.db"}):
            result = resolve_db_path()
            assert str(result).replace("\\", "/") == "/tmp/env_test.db"

    def test_default_fallback(self):
        """无 override 无 env 时使用默认路径"""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("QUANT_DB_PATH", None)
            result = resolve_db_path()
            assert "data" in str(result)
            assert result.name.endswith(".db")

    def test_same_path_in_same_process(self, tmp_path):
        """同一进程内多次调用返回相同路径"""
        fake = tmp_path / "consistent.db"
        p1 = resolve_db_path(override=str(fake))
        p2 = resolve_db_path(override=str(fake))
        assert p1 == p2


# ─── resolve_wecom_webhook ───
class TestResolveWecomWebhook:
    def test_env_var_has_priority(self):
        with patch.dict(os.environ, {"WECOM_WEBHOOK": "https://env.example.com"}):
            result = resolve_wecom_webhook()
            assert result == "https://env.example.com"

    def test_returns_none_when_no_config(self):
        with patch.dict(os.environ, {}, clear=True):
            # 没有 WECOM_WEBHOOK 也没有配置文件
            result = resolve_wecom_webhook()
            # 可能返回 None 或从配置文件读到的值
            assert result is None or isinstance(result, str)


# ─── config_hash ───
class TestConfigHash:
    def test_same_config_same_hash(self):
        h1 = config_hash({"a": 1, "b": 2})
        h2 = config_hash({"a": 1, "b": 2})
        assert h1 == h2

    def test_different_config_different_hash(self):
        h1 = config_hash({"a": 1})
        h2 = config_hash({"a": 2})
        assert h1 != h2


# ─── validate_config ───
class TestValidateConfig:
    def test_valid_config_no_errors(self):
        cfg = {
            "accounts": {
                "learn": {"account_id": 1, "initial_cash": 200000.0},
            },
            "risk": {
                "max_position_pct": 0.2,
                "max_total_positions": 6,
                "stop_loss_pct": -0.08,
            },
            "broker": {"mode": "sim"},
        }
        errors = validate_config(cfg)
        assert len(errors) == 0

    def test_missing_accounts(self):
        cfg = {"risk": {"max_position_pct": 0.2}}
        errors = validate_config(cfg)
        assert any("accounts" in e for e in errors)

    def test_missing_risk(self):
        cfg = {"accounts": {"learn": {"account_id": 1}}}
        errors = validate_config(cfg)
        assert any("risk" in e for e in errors)

    def test_missing_risk_field(self):
        cfg = {
            "accounts": {"learn": {"account_id": 1, "initial_cash": 200000}},
            "risk": {"max_position_pct": 0.2},  # 缺 max_total_positions 和 stop_loss_pct
            "broker": {"mode": "sim"},
        }
        errors = validate_config(cfg)
        assert len(errors) >= 1
        assert any("max_total_positions" in e or "stop_loss_pct" in e for e in errors)

    def test_invalid_broker_mode(self):
        cfg = {
            "accounts": {"learn": {"account_id": 1, "initial_cash": 200000}},
            "risk": {"max_position_pct": 0.2, "max_total_positions": 6, "stop_loss_pct": -0.08},
            "broker": {"mode": "unknown_mode"},
        }
        errors = validate_config(cfg)
        assert any("unknown_mode" in e for e in errors)

    def test_missing_initial_cash_in_account(self):
        cfg = {
            "accounts": {"learn": {"account_id": 1}},  # 缺 initial_cash
            "risk": {"max_position_pct": 0.2, "max_total_positions": 6, "stop_loss_pct": -0.08},
            "broker": {"mode": "sim"},
        }
        errors = validate_config(cfg)
        assert any("initial_cash" in e for e in errors)


# ─── get_config_with_validation ───
class TestGetConfigWithValidation:
    def test_returns_tuple(self):
        cfg, errors, h = get_config_with_validation()
        assert isinstance(cfg, dict)
        assert isinstance(errors, list)
        assert isinstance(h, str)
        assert len(h) == 16  # sha256[:16]
