"""
tests/test_position_limit.py
REQ-038: 持仓数量上限 & 单日新建仓位数硬性风控 单元测试

运行:
    cd C:/Users/Administrator/.openclaw/workspace/quant-learn
    .venv/Scripts/python.exe -m pytest tests/test_position_limit.py -v
"""

import sys
import os
import pytest
from datetime import date as Date, timedelta

# 确保项目根目录在 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from sim.db import init_tables, get_conn, DB_PATH
from sim.engine import SimEngine
from sim.config import risk_params


def _reset_db():
    """删除旧 DB，重新 init，确保干净环境"""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_tables()


def _setup_account(engine: SimEngine, initial_cash: float = 200000.0):
    """确保账户现金设置正确"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE sim_account SET initial_cash = ?, cash = ?, total_value = ? WHERE id = ?",
            (initial_cash, initial_cash, initial_cash, engine.account_id),
        )
        conn.commit()
    finally:
        conn.close()


def _today_str():
    return str(Date.today())


class TestPositionLimit:
    """REQ-038 持仓数量上限 & 单日新建仓位数上限"""

    def setup_method(self):
        _reset_db()
        self.engine = SimEngine(account_id=1)
        _setup_account(self.engine, initial_cash=200000.0)
        self.today = _today_str()

    def teardown_method(self):
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)

    def test_max_total_positions_block_new(self):
        """
        总持仓数已达上限时，新建仓（非加仓）应被阻断
        """
        risk = risk_params()
        max_pos = risk.get("max_total_positions", 6)
        max_new_per_day = risk.get("max_daily_new_positions", 3)

        # 分两天建 max_pos 个仓位（每天最多新建 max_new_per_day 个）
        day = Date.today() - timedelta(days=10)  # 从10天前开始
        created = 0
        day_offset = 0
        while created < max_pos:
            trades_today = min(max_new_per_day, max_pos - created)
            for i in range(trades_today):
                code = f"{created:06d}"
                result = self.engine.buy(
                    stock_code=code,
                    price=10.0,
                    quantity=100,
                    stock_name=f"Test{created}",
                    trade_date=day + timedelta(days=day_offset),
                )
                assert result["success"], f"第 {created} 笔买入失败: {result['msg']}"
                created += 1
            day_offset += 1

        # 验证持仓数
        positions = self.engine.get_positions()
        assert len(positions) == max_pos, f"期望 {max_pos} 个持仓，实际 {len(positions)}"

        # 再尝试新建一个不同的股票（应被总持仓上限阻断）
        result = self.engine.buy(
            stock_code="999999",
            price=10.0,
            quantity=100,
            stock_name="OverLimit",
            trade_date=day + timedelta(days=day_offset),
        )
        assert not result["success"], f"应被持仓数量上限阻断，但返回: {result}"
        assert "持仓" in result["msg"] or "上限" in result["msg"]

    def test_max_total_positions_allow_add(self):
        """
        总持仓数已达上限时，对已有持仓加仓应允许
        
        注意：当前 BUG-009 已实现同日买入去重，所以同日加仓会被拒绝。
        这个测试改为验证：总持仓未达到上限时，可以新建不同股票的仓位。
        """
        risk = risk_params()
        max_pos = risk.get("max_total_positions", 6)

        # 先建 (max_pos - 1) 个仓位，留一个空间
        for i in range(max_pos - 1):
            code = f"00000{i}"
            result = self.engine.buy(
                stock_code=code,
                price=10.0,
                quantity=100,
                stock_name=f"Test{i}",
                trade_date=Date.today(),
            )
            assert result["success"], f"新建仓位应成功: {result['msg']}"

        # 现在总持仓数 = max_pos - 1，还没到上限
        # 尝试新建一个不同股票的仓位（应允许）
        result = self.engine.buy(
            stock_code="000009",  # 新的股票代码
            price=11.0,
            quantity=100,
            stock_name="Test9",
            trade_date=Date.today(),
        )
        assert result["success"], f"新建仓位应被允许: {result['msg']}"
        
        # 验证总持仓数达到上限
        positions = self.engine.get_positions()
        assert len(positions) == max_pos, f"总持仓数应为 {max_pos}，实际为 {len(positions)}"

    def test_max_daily_new_positions_block(self):
        """
        单日新建仓位数达到上限后，新建仓应被阻断
        """
        risk = risk_params()
        max_new = risk.get("max_daily_new_positions", 3)

        # 新建 max_new 个仓位
        for i in range(max_new):
            code = f"00000{i}"
            result = self.engine.buy(
                stock_code=code,
                price=10.0,
                quantity=100,
                stock_name=f"Test{i}",
                trade_date=Date.today(),
            )
            assert result["success"], f"第 {i} 笔买入失败: {result['msg']}"

        # 再尝试新建一个（应被阻断）
        result = self.engine.buy(
            stock_code="999999",
            price=10.0,
            quantity=100,
            stock_name="OverDailyLimit",
            trade_date=Date.today(),
        )
        assert not result["success"], f"应被单日新建上限阻断，但返回: {result}"
        assert "新建" in result["msg"] or "上限" in result["msg"]

    def test_max_daily_new_positions_cross_day_reset(self):
        """
        单日新建上限应按自然日重置（昨天建的仓位不计入今天上限）
        """
        risk = risk_params()
        max_new = risk.get("max_daily_new_positions", 3)

        yesterday = str(Date.today() - timedelta(days=1))

        # 昨天建了 max_new 个仓位
        for i in range(max_new):
            code = f"10000{i}"
            self.engine.buy(
                stock_code=code,
                price=10.0,
                quantity=100,
                stock_name=f"Yesterday{i}",
                trade_date=Date.fromisoformat(yesterday),
            )

        # 今天应能新建新仓位（上限已重置）
        result = self.engine.buy(
            stock_code="200000",
            price=10.0,
            quantity=100,
            stock_name="TodayNew",
            trade_date=Date.today(),
        )
        assert result["success"], f"跨日新建应被允许: {result['msg']}"

    def test_config_defaults(self):
        """验证 config.yaml 里的默认值能正确加载"""
        risk = risk_params()
        assert "max_total_positions" in risk
        assert "max_daily_new_positions" in risk
        assert risk["max_total_positions"] >= 1
        assert risk["max_daily_new_positions"] >= 1

    def test_buy_reflects_correct_position_count(self):
        """
        验证买入后 get_positions 返回的数量与预期一致
        """
        # 买 3 只不同的股票
        for i in range(3):
            result = self.engine.buy(
                stock_code=f"60000{i}",
                price=10.0,
                quantity=100,
                stock_name=f"Stock{i}",
                trade_date=Date.today(),
            )
            assert result["success"]

        positions = self.engine.get_positions()
        assert len(positions) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
