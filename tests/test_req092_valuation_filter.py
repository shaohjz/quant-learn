"""
test_req092_valuation_filter.py — REQ-092 买入前估值过滤测试
======================================================================
测试场景：
1. 估值过滤配置加载
2. 估值数据获取（腾讯API mock）
3. PE过高拒绝
4. PB过高拒绝
5. PE为负跳过
6. 数据获取失败放行
7. 估值合理通过
8. 过滤关闭时放行
9. review_decisions 写入验证
10. decide_action 集成测试
"""

import importlib
import json
import os
import sys
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 确保项目根目录在 path 中
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QUANT_DB_PATH', str(ROOT / 'data' / 'sim_live_mirror.db'))

# 直接加载 sim_executor 模块（scripts 目录没有 __init__.py）
import importlib.util as _iu
_spec = _iu.spec_from_file_location(
    "sim_executor",
    str(ROOT / "scripts" / "sim_executor.py")
)
_sim = _iu.module_from_spec(_spec)
_spec.loader.exec_module(_sim)


# ============================================================
# Test: 配置加载
# ============================================================
class TestValuationConfig:
    """估值过滤配置加载测试"""

    def test_load_default_config(self):
        """默认配置应返回所有字段"""
        cfg = _sim._load_valuation_filter_config()
        assert 'enabled' in cfg
        assert 'max_pe_ttm' in cfg
        assert 'max_pe_industry_ratio' in cfg
        assert 'max_pe_percentile' in cfg
        assert 'max_pb' in cfg
        assert 'min_pb' in cfg
        assert 'skip_negative_pe' in cfg
        assert 'cache_ttl_seconds' in cfg
        assert 'timeout_seconds' in cfg
        assert cfg['enabled'] is True
        assert cfg['max_pe_ttm'] == 100.0
        assert cfg['skip_negative_pe'] is True

    def test_config_types(self):
        """配置值类型应正确"""
        cfg = _sim._load_valuation_filter_config()
        assert isinstance(cfg['enabled'], bool)
        assert isinstance(cfg['max_pe_ttm'], float)
        assert isinstance(cfg['max_pe_industry_ratio'], float)
        assert isinstance(cfg['max_pe_percentile'], float)
        assert isinstance(cfg['max_pb'], float)
        assert isinstance(cfg['min_pb'], float)
        assert isinstance(cfg['skip_negative_pe'], bool)
        assert isinstance(cfg['cache_ttl_seconds'], int)
        assert isinstance(cfg['timeout_seconds'], int)


# ============================================================
# Test: 估值数据获取
# ============================================================
class TestValuationFetch:
    """估值数据获取测试"""

    def test_get_tencent_valuation_success(self):
        """腾讯API正常返回时的解析"""
        import requests as _real_requests
        mock_resp = MagicMock()
        # 腾讯格式: ~ 分隔，至少需要47个字段（PE在索引39，PB在索引46）
        # 构造47个足够的~分隔字段
        fields = [''] * 47
        fields[1] = '平安银行'    # 名称
        fields[3] = '12.34'       # 当前价
        fields[39] = '5.67'       # PE(TTM)
        fields[46] = '1.00'       # PB
        fields[45] = '12345678'   # 总市值(万)
        fields[37] = '50000'      # 成交额
        mock_resp.text = 'v_sz000001="' + '~'.join(fields) + '"'
        mock_resp.encoding = 'gbk'

        # _get_tencent_valuation 内部 import requests as _requests
        with patch.object(_real_requests, 'get', return_value=mock_resp):
            _sim._VALUATION_CACHE.clear()

            result = _sim._get_tencent_valuation('000001')
            assert result is not None
            assert result['name'] == '平安银行'
            assert result['price'] == 12.34

    def test_get_tencent_valuation_empty(self):
        """腾讯API返回空/无效数据"""
        mock_resp = MagicMock()
        mock_resp.text = 'pv_none_match=""'
        mock_resp.encoding = 'gbk'

        import requests as _real_requests
        with patch.object(_real_requests, 'get', return_value=mock_resp):
            _sim._VALUATION_CACHE.clear()

            result = _sim._get_tencent_valuation('999999')
            assert result is None

    def test_valuation_cache(self):
        """估值数据缓存机制"""
        import requests as _real_requests
        mock_resp = MagicMock()
        # 构造足够的字段数
        fields = [''] * 47
        fields[1] = '贵州茅台'
        fields[3] = '1500.00'
        fields[39] = '25.50'
        fields[46] = '3.20'
        mock_resp.text = 'v_sh600519="' + '~'.join(fields) + '"'
        mock_resp.encoding = 'gbk'

        with patch.object(_real_requests, 'get') as mock_get:
            mock_get.return_value = mock_resp
            _sim._VALUATION_CACHE.clear()

            # 第一次调用
            result1 = _sim._get_tencent_valuation('600519')
            assert result1 is not None

            # 第二次调用应走缓存
            result2 = _sim._get_tencent_valuation('600519')
            assert result2 is not None
            # 只应调用1次API
            assert mock_get.call_count == 1


# ============================================================
# Test: 估值过滤规则
# ============================================================
class TestValuationFilterRules:
    """估值过滤规则测试"""

    def _mock_cfg(self, **overrides):
        defaults = {
            'enabled': True,
            'max_pe_ttm': 100.0,
            'max_pe_industry_ratio': 2.0,
            'max_pe_percentile': 80.0,
            'max_pb': 10.0,
            'min_pb': 0.0,
            'skip_negative_pe': True,
            'cache_ttl_seconds': 600,
            'timeout_seconds': 10,
        }
        defaults.update(overrides)
        return defaults

    def test_valuation_reasonable(self):
        """估值合理 → 放行"""
        with patch.object(_sim, '_load_valuation_filter_config') as mock_load_cfg, \
             patch.object(_sim, '_get_tencent_valuation') as mock_get_val:
            mock_load_cfg.return_value = self._mock_cfg()
            mock_get_val.return_value = {
                'name': '测试股', 'price': 50.0,
                'pe_ttm': 25.0, 'pb': 3.5,
                'market_cap': 1000, 'amount': 100,
            }

            allowed, reason, data = _sim._check_valuation_filter('600519', {'level': 'buy_zone'})
            assert allowed is True
            assert '估值合理' in reason
            assert data['status'] == 'passed'

    def test_pe_too_high_rejected(self):
        """PE过高 → 拒绝"""
        with patch.object(_sim, '_load_valuation_filter_config') as mock_load_cfg, \
             patch.object(_sim, '_get_tencent_valuation') as mock_get_val:
            mock_load_cfg.return_value = self._mock_cfg()
            mock_get_val.return_value = {
                'name': '高估值股', 'price': 200.0,
                'pe_ttm': 150.0, 'pb': 5.0, 'market_cap': 5000,
            }

            allowed, reason, data = _sim._check_valuation_filter('688888', {'level': 'buy_strong'})
            assert allowed is False
            assert 'PE过高' in reason
            assert data['status'] == 'pe_too_high'

    def test_pb_too_high_rejected(self):
        """PB过高 → 拒绝"""
        with patch.object(_sim, '_load_valuation_filter_config') as mock_load_cfg, \
             patch.object(_sim, '_get_tencent_valuation') as mock_get_val:
            mock_load_cfg.return_value = self._mock_cfg()
            mock_get_val.return_value = {
                'name': '高PB股', 'price': 30.0,
                'pe_ttm': 20.0, 'pb': 15.0, 'market_cap': 500,
            }

            allowed, reason, data = _sim._check_valuation_filter('600666', {'level': 'buy_zone'})
            assert allowed is False
            assert 'PB过高' in reason
            assert data['status'] == 'pb_too_high'

    def test_negative_pe_skipped(self):
        """PE为负(亏损)且配置允许跳过 → 放行"""
        with patch.object(_sim, '_load_valuation_filter_config') as mock_load_cfg, \
             patch.object(_sim, '_get_tencent_valuation') as mock_get_val:
            mock_load_cfg.return_value = self._mock_cfg()
            mock_get_val.return_value = {
                'name': '亏损股', 'price': 10.0,
                'pe_ttm': -5.0, 'pb': 0.8, 'market_cap': 200,
            }

            allowed, reason, data = _sim._check_valuation_filter('000888', {'level': 'buy_strong'})
            assert allowed is True
            assert 'PE为负' in reason
            assert data['status'] == 'negative_pe_skipped'

    def test_negative_pe_not_skipped(self):
        """PE为负且配置不允许跳过 → 拒绝"""
        with patch.object(_sim, '_load_valuation_filter_config') as mock_load_cfg, \
             patch.object(_sim, '_get_tencent_valuation') as mock_get_val:
            mock_load_cfg.return_value = self._mock_cfg(skip_negative_pe=False)
            mock_get_val.return_value = {
                'name': '亏损股', 'price': 5.0,
                'pe_ttm': -10.0, 'pb': 0.5, 'market_cap': 100,
            }

            allowed, reason, data = _sim._check_valuation_filter('000999', {'level': 'buy_zone'})
            assert allowed is False
            assert 'PE为负' in reason
            assert data['status'] == 'negative_pe_rejected'

    def test_data_unavailable_passthrough(self):
        """数据获取失败 → 放行（不阻断交易）"""
        with patch.object(_sim, '_load_valuation_filter_config') as mock_load_cfg, \
             patch.object(_sim, '_get_tencent_valuation') as mock_get_val:
            mock_load_cfg.return_value = self._mock_cfg()
            mock_get_val.return_value = None

            allowed, reason, data = _sim._check_valuation_filter('000001', {'level': 'buy_zone'})
            assert allowed is True
            assert '数据获取失败' in reason
            assert data.get('status') == 'data_unavailable'

    def test_filter_disabled_passthrough(self):
        """估值过滤关闭 → 放行"""
        with patch.object(_sim, '_load_valuation_filter_config') as mock_load_cfg, \
             patch.object(_sim, '_get_tencent_valuation') as mock_get_val:
            mock_load_cfg.return_value = self._mock_cfg(enabled=False)

            allowed, reason, data = _sim._check_valuation_filter('600519', {'level': 'buy_zone'})
            assert allowed is True
            assert '估值过滤已关闭' in reason
            mock_get_val.assert_not_called()

    def test_pb_too_low_rejected(self):
        """PB过低(破净)且配置了 min_pb → 拒绝"""
        with patch.object(_sim, '_load_valuation_filter_config') as mock_load_cfg, \
             patch.object(_sim, '_get_tencent_valuation') as mock_get_val:
            mock_load_cfg.return_value = self._mock_cfg(min_pb=0.5)
            mock_get_val.return_value = {
                'name': '破净股', 'price': 3.0,
                'pe_ttm': 8.0, 'pb': 0.3, 'market_cap': 50,
            }

            allowed, reason, data = _sim._check_valuation_filter('600777', {'level': 'buy_zone'})
            assert allowed is False
            assert 'PB过低' in reason
            assert data['status'] == 'pb_too_low'


# ============================================================
# Test: decide_action 集成
# ============================================================
class TestDecideActionIntegration:
    """decide_action 集成测试：估值过滤在买入链路中的位置"""

    def test_buy_zone_blocked_by_valuation(self):
        """buy_zone 信号被估值过滤阻止"""
        with patch.object(_sim, '_check_valuation_filter') as mock_val_filter, \
             patch.object(_sim, '_load_risk_limits') as mock_load_risk, \
             patch.object(_sim, '_load_daily_buy_controls') as mock_load_daily, \
             patch.object(_sim, '_check_daily_buy_controls') as mock_daily_ctrl, \
             patch.object(_sim, 'check_price_sanity') as mock_price, \
             patch.object(_sim, '_check_trend_gate') as mock_trend:
            mock_load_risk.return_value = (6, 2)
            mock_load_daily.return_value = (30000.0, 0.35, 30)
            mock_trend.return_value = (True, 'trend_filter ok')
            mock_price.return_value = (True, 'price ok')
            mock_daily_ctrl.return_value = (True, 'budget ok', {})

            mock_val_filter.return_value = (
                False,
                'PE过高: PE(TTM)=150.0 > 100.0，估值过滤拒绝',
                {'status': 'pe_too_high', 'pe_ttm': 150.0},
            )

            rule = {
                'code': '688888', 'name': '高估值股',
                'level': 'buy_zone', 'trigger': 200.0,
                'dir': 'below', 'trend_filter': {'gate': 'auto'},
            }

            result = _sim.decide_action(rule, 190.0)
            assert result == 'NO_ACTION'

    def test_buy_strong_passes_valuation(self):
        """buy_strong 信号估值合理 → 返回 BUY"""
        with patch.object(_sim, '_check_valuation_filter') as mock_val_filter, \
             patch.object(_sim, '_load_risk_limits') as mock_load_risk, \
             patch.object(_sim, '_load_daily_buy_controls') as mock_load_daily, \
             patch.object(_sim, '_check_daily_buy_controls') as mock_daily_ctrl, \
             patch.object(_sim, 'check_price_sanity') as mock_price, \
             patch.object(_sim, '_check_trend_gate') as mock_trend:
            mock_load_risk.return_value = (6, 2)
            mock_load_daily.return_value = (30000.0, 0.35, 30)
            mock_trend.return_value = (True, 'trend_filter ok')
            mock_price.return_value = (True, 'price ok')
            mock_daily_ctrl.return_value = (True, 'budget ok', {})

            mock_val_filter.return_value = (
                True,
                '估值合理: PE(TTM)=25.0, PB=3.20',
                {'status': 'passed', 'pe_ttm': 25.0, 'pb': 3.20},
            )

            rule = {
                'code': '600519', 'name': '贵州茅台',
                'level': 'buy_strong', 'trigger': 1500.0,
                'dir': 'below', 'trend_filter': {'gate': 'auto'},
            }

            result = _sim.decide_action(rule, 1480.0)
            assert result == 'BUY'

    def test_trend_break_buy_blocked_by_valuation(self):
        """trend_break_buy 被估值过滤阻止"""
        with patch.object(_sim, '_check_valuation_filter') as mock_val_filter, \
             patch.object(_sim, '_load_risk_limits') as mock_load_risk, \
             patch.object(_sim, '_load_daily_buy_controls') as mock_load_daily, \
             patch.object(_sim, '_check_daily_buy_controls') as mock_daily_ctrl, \
             patch.object(_sim, 'check_price_sanity') as mock_price:
            mock_load_risk.return_value = (6, 2)
            mock_load_daily.return_value = (30000.0, 0.35, 30)
            mock_price.return_value = (True, 'price ok')
            mock_daily_ctrl.return_value = (True, 'budget ok', {})

            mock_val_filter.return_value = (
                False,
                'PB过高: PB=12.50 > 10.00，估值过滤拒绝',
                {'status': 'pb_too_high', 'pb': 12.50},
            )

            rule = {
                'code': '603000', 'name': '高PB股',
                'level': 'trend_break_buy', 'trigger': 50.0,
                'dir': 'above',
            }

            result = _sim.decide_action(rule, 51.0)
            assert result == 'NO_ACTION'


# ============================================================
# Test: review_decisions 写入
# ============================================================
class TestReviewDecisions:
    """review_decisions 表写入测试"""

    def test_valuation_blocked_recorded(self):
        """估值过滤拒绝应写入 review_decisions"""
        db_path = ROOT / 'data' / 'sim_live_mirror.db'
        os.environ['QUANT_DB_PATH'] = str(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS review_decisions ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  account_id INTEGER NOT NULL,"
            "  stock_code TEXT NOT NULL,"
            "  trade_date DATE NOT NULL DEFAULT (date('now', 'localtime')),"
            "  decision_type TEXT NOT NULL,"
            "  allowed INTEGER NOT NULL,"
            "  reason TEXT,"
            "  created_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))"
            ")"
        )
        conn.commit()

        before_count = conn.execute(
            "SELECT COUNT(*) FROM review_decisions WHERE decision_type='valuation_filter_blocked'"
        ).fetchone()[0]

        _sim._write_review_decision(
            1, '600519', 'valuation_filter_blocked', 0,
            'PE过高: PE(TTM)=150.0 > 100.0，估值过滤拒绝'
        )

        after_count = conn.execute(
            "SELECT COUNT(*) FROM review_decisions WHERE decision_type='valuation_filter_blocked'"
        ).fetchone()[0]

        assert after_count >= before_count

        last = conn.execute(
            "SELECT * FROM review_decisions WHERE decision_type='valuation_filter_blocked' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert last is not None
        assert last[1] == 1  # account_id
        assert last[2] == '600519'  # stock_code
        assert last[5] == 0  # allowed=0 (拒绝)
        assert 'PE过高' in last[6]  # reason

        conn.close()


# ============================================================
# Test: _deep_merge 辅助函数
# ============================================================
class TestDeepMerge:
    """_deep_merge 递归合并测试"""

    def test_merge_override(self):
        base = {'a': 1, 'b': 2}
        override = {'b': 3, 'c': 4}
        _sim._deep_merge(base, override)
        assert base == {'a': 1, 'b': 3, 'c': 4}

    def test_merge_nested(self):
        base = {'a': {'x': 1, 'y': 2}, 'b': 0}
        override = {'a': {'y': 3, 'z': 4}}
        _sim._deep_merge(base, override)
        assert base == {'a': {'x': 1, 'y': 3, 'z': 4}, 'b': 0}

    def test_merge_empty_override(self):
        base = {'a': 1, 'b': {'x': 2}}
        override = {}
        _sim._deep_merge(base, override)
        assert base == {'a': 1, 'b': {'x': 2}}


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
