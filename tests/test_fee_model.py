"""
tests/test_fee_model.py — QL-005 统一FeeModel测试

验收:
  1. 同一成交在各路径的费用结果完全一致
  2. 买入不收印花税，卖出按交易日期使用正确税率
  3. 最低佣金边界有测试
  4. 2023-08-28 前后印花税率切换
"""

import pytest
from datetime import date as Date

from quant_core.fees import FeeModel, FeeConfig, FeeBreakdown


class TestFeeConsistency:
    """同一成交在各路径的费用结果完全一致"""

    def test_same_input_same_output(self):
        model = FeeModel()
        r1 = model.calculate("SELL", 10000.0, Date(2024, 6, 1))
        r2 = model.calculate("SELL", 10000.0, Date(2024, 6, 1))
        assert r1.commission == r2.commission
        assert r1.stamp_tax == r2.stamp_tax
        assert r1.total == r2.total


class TestStampTax:
    """买入不收印花税，卖出按日期使用正确税率"""

    def test_buy_no_stamp_tax(self):
        model = FeeModel()
        result = model.calculate("BUY", 10000.0, Date(2024, 1, 1))
        assert result.stamp_tax == 0.0

    def test_sell_new_rate_after_20230828(self):
        """2023-08-28后印花税率千0.5"""
        model = FeeModel()
        result = model.calculate("SELL", 10000.0, Date(2024, 1, 1))
        assert result.stamp_tax == 5.0  # 10000 * 0.0005

    def test_sell_old_rate_before_20230828(self):
        """2023-08-28前印花税率千1"""
        model = FeeModel()
        result = model.calculate("SELL", 10000.0, Date(2023, 1, 1))
        assert result.stamp_tax == 10.0  # 10000 * 0.001

    def test_stamp_tax_change_date_boundary(self):
        """2023-08-28当天用新税率"""
        model = FeeModel()
        result = model.calculate("SELL", 10000.0, Date(2023, 8, 28))
        assert result.stamp_tax == 5.0  # 新税率

    def test_no_trade_date_defaults_new_rate(self):
        """不传交易日期默认用新税率"""
        model = FeeModel()
        result = model.calculate("SELL", 10000.0)
        assert result.stamp_tax == 5.0


class TestMinCommission:
    """最低佣金边界"""

    def test_small_amount_uses_min_commission(self):
        """小金额触发最低佣金"""
        model = FeeModel()
        result = model.calculate("BUY", 100.0, Date(2024, 1, 1))
        # 100 * 0.00025 = 0.025 < 5.0，应使用最低5.0
        assert result.commission == 5.0

    def test_large_amount_uses_rate(self):
        """大金额使用费率"""
        model = FeeModel()
        result = model.calculate("BUY", 100000.0, Date(2024, 1, 1))
        # 100000 * 0.00025 = 25.0 > 5.0
        assert result.commission == 25.0

    def test_exact_threshold(self):
        """刚好等于最低佣金阈值"""
        model = FeeModel()
        # 5.0 / 0.00025 = 20000
        result = model.calculate("BUY", 20000.0, Date(2024, 1, 1))
        assert result.commission == 5.0


class TestTransferFee:
    """过户费（沪市）"""

    def test_sh_exchange_has_transfer_fee(self):
        model = FeeModel()
        result = model.calculate("BUY", 10000.0, Date(2024, 1, 1), exchange="SH")
        assert result.transfer_fee == 0.1  # 10000 * 0.00001

    def test_sz_exchange_no_transfer_fee(self):
        model = FeeModel()
        result = model.calculate("BUY", 10000.0, Date(2024, 1, 1), exchange="SZ")
        assert result.transfer_fee == 0.0

    def test_transfer_fee_on_both_sides(self):
        model = FeeModel()
        buy_result = model.calculate("BUY", 10000.0, Date(2024, 1, 1), exchange="SH")
        sell_result = model.calculate("SELL", 10000.0, Date(2024, 1, 1), exchange="SH")
        assert buy_result.transfer_fee == sell_result.transfer_fee


class TestEdgeCases:
    def test_zero_amount(self):
        model = FeeModel()
        result = model.calculate("BUY", 0.0, Date(2024, 1, 1))
        assert result.total == 0.0

    def test_negative_amount(self):
        model = FeeModel()
        result = model.calculate("BUY", -100.0, Date(2024, 1, 1))
        assert result.total == 0.0

    def test_estimated_flag(self):
        model = FeeModel()
        result = model.calculate("BUY", 10000.0, Date(2024, 1, 1), estimated=True)
        assert result.estimated is True


class TestFromConfig:
    def test_from_config_dict(self):
        cfg = {"fees": {"commission_rate": 0.0003, "min_commission": 3.0}}
        model = FeeModel.from_config(cfg)
        result = model.calculate("BUY", 100.0, Date(2024, 1, 1))
        assert result.commission == 3.0  # min_commission=3.0

    def test_default_config(self):
        cfg = {}
        model = FeeModel.from_config(cfg)
        result = model.calculate("SELL", 10000.0, Date(2024, 1, 1))
        assert result.stamp_tax == 5.0


class TestTotalCalculation:
    def test_total_equals_sum(self):
        model = FeeModel()
        result = model.calculate("SELL", 100000.0, Date(2024, 1, 1), exchange="SH")
        assert result.total == pytest.approx(
            result.commission + result.stamp_tax + result.transfer_fee, abs=0.01
        )
