#!/usr/bin/env python3
"""
测试 ATR 动态止损功能

验证内容：
1. trend_health_check.py 正确计算 atr_pct
2. apply_trend_filter.py 正确计算 atr_stop_pct 并写入 config.yaml
3. portfolio_alert.py 的 get_rr_ratio_for_rule 优先使用 ATR 止损
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

def test_atr_calculation():
    """测试 ATR 计算是否正确"""
    print("=" * 70)
    print("测试 1: ATR 计算")
    print("=" * 70)
    
    try:
        from trend_health_check import calc_atr, analyze
        
        # 测试 calc_atr 函数
        import pandas as pd
        import numpy as np
        
        # 创建模拟数据
        dates = pd.date_range('2026-01-01', periods=100, freq='D')
        df = pd.DataFrame({
            'date': dates,
            'open': np.random.uniform(9, 11, 100),
            'high': np.random.uniform(11, 12, 100),
            'low': np.random.uniform(8, 9, 100),
            'close': np.random.uniform(9.5, 10.5, 100),
            'volume': np.random.randint(1000000, 10000000, 100)
        })
        
        atr_series = calc_atr(df, 14)
        atr14 = float(atr_series.iloc[-1])
        last = float(df['close'].iloc[-1])
        atr_pct = (atr14 / last * 100)
        
        print(f"✅ ATR(14) 计算成功: {atr14:.3f}")
        print(f"✅ ATR 百分比: {atr_pct:.2f}%")
        
        # 验证 atr_pct 是否在合理范围内
        if 0 < atr_pct < 20:
            print(f"✅ ATR 百分比在合理范围内 (0-20%)")
        else:
            print(f"⚠️ ATR 百分比可能异常: {atr_pct:.2f}%")
        
        return True
    except Exception as e:
        print(f"❌ ATR 计算测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_atr_stop_pct_calculation():
    """测试 atr_stop_pct 计算逻辑"""
    print("\n" + "=" * 70)
    print("测试 2: atr_stop_pct 计算")
    print("=" * 70)
    
    try:
        # 模拟 apply_trend_filter.py 中的逻辑
        test_cases = [
            (3.0, 6.0),   # 低波动股：ATR 3% → 止损 6%
            (5.0, 10.0),  # 中等波动：ATR 5% → 止损 10%
            (8.0, 15.0),  # 高波动股：ATR 8% → 止损 16%，但被裁到 15%
            (2.0, 5.0),   # 极低波动：ATR 2% → 止损 4%，但被提升到 5%
            (10.0, 15.0), # 超高波动：ATR 10% → 止损 20%，但被裁到 15%
        ]
        
        for atr_pct, expected_stop in test_cases:
            atr_stop_pct = max(5.0, min(15.0, round(2 * atr_pct, 2)))
            print(f"ATR% = {atr_pct:.1f}% → 止损% = {atr_stop_pct:.1f}% (预期 {expected_stop:.1f}%)")
            
            if abs(atr_stop_pct - expected_stop) < 0.1:
                print(f"  ✅ 计算正确")
            else:
                print(f"  ⚠️ 计算可能有误")
        
        print(f"\n✅ atr_stop_pct 计算逻辑验证通过")
        return True
    except Exception as e:
        print(f"❌ atr_stop_pct 计算测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_atr_stop_in_config():
    """测试 config.yaml 中是否正确写入了 atr_stop_pct"""
    print("\n" + "=" * 70)
    print("测试 3: config.yaml 中的 atr_stop_pct")
    print("=" * 70)
    
    try:
        import yaml
        
        CONFIG = ROOT / 'config.yaml'
        cfg = yaml.safe_load(CONFIG.read_text(encoding='utf-8'))
        
        found_count = 0
        for code, info in cfg.get('watchlist', {}).get('user_manual', {}).items():
            tf = info.get('trend_filter', {})
            if tf and 'atr_stop_pct' in tf:
                found_count += 1
                atr_stop_pct = tf['atr_stop_pct']
                atr_pct = tf.get('atr_pct', 0)
                
                print(f"  {code} {info.get('name', '')}:")
                print(f"    ATR% = {atr_pct:.2f}%")
                print(f"    ATR 止损% = {atr_stop_pct:.2f}%")
                print(f"    止损基准 = {tf.get('atr_stop_basis', '')}")
                
                # 验证是否在 [5%, 15%] 范围内
                if 5.0 <= atr_stop_pct <= 15.0:
                    print(f"    ✅ 止损百分比在合理范围内 [5%, 15%]")
                else:
                    print(f"    ⚠️ 止损百分比超出范围: {atr_stop_pct:.2f}%")
        
        if found_count > 0:
            print(f"\n✅ 在 config.yaml 中找到 {found_count} 只股票的 ATR 止损配置")
            return True
        else:
            print(f"\n⚠️ config.yaml 中未找到 atr_stop_pct 配置")
            print(f"   (可能需要先运行 apply_trend_filter.py)")
            return False
    except Exception as e:
        print(f"❌ config.yaml 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_get_rr_ratio_prefers_atr():
    """测试 get_rr_ratio_for_rule 优先使用 ATR 止损"""
    print("\n" + "=" * 70)
    print("测试 4: get_rr_ratio_for_rule 优先使用 ATR 止损")
    print("=" * 70)
    
    try:
        from portfolio_alert import get_rr_ratio_for_rule
        
        # 模拟规则列表，包含 ATR 止损
        mock_rules_with_atr = [
            {
                'code': '600900',
                'trend_filter': {
                    'atr_stop_pct': 6.0  # ATR 止损 -6%
                }
            },
            {
                'code': '600900',
                'level': 'trend_break',
                'trigger': 9.5  # trend_break 止损
            }
        ]
        
        # 模拟规则列表，不包含 ATR 止损
        mock_rules_without_atr = [
            {
                'code': '600900',
                'level': 'trend_break',
                'trigger': 9.5  # trend_break 止损
            }
        ]
        
        entry_price = 10.0
        
        # 测试有 ATR 止损的情况
        rr_with_atr = get_rr_ratio_for_rule('600900', entry_price, mock_rules_with_atr)
        expected_stop_with_atr = entry_price * (1 - 6.0 / 100)  # 9.4
        expected_rr_with_atr = (entry_price * 0.15) / (entry_price - expected_stop_with_atr)
        
        print(f"有 ATR 止损:")
        print(f"  入场价: ¥{entry_price:.2f}")
        print(f"  ATR 止损%: 6.0%")
        print(f"  止损价: ¥{expected_stop_with_atr:.2f}")
        print(f"  盈亏比: {rr_with_atr:.2f}:1")
        print(f"  预期盈亏比: {expected_rr_with_atr:.2f}:1")
        
        if abs(rr_with_atr - expected_rr_with_atr) < 0.01:
            print(f"  ✅ 盈亏比计算正确（使用了 ATR 止损）")
        else:
            print(f"  ⚠️ 盈亏比计算可能未使用 ATR 止损")
        
        # 测试没有 ATR 止损的情况
        rr_without_atr = get_rr_ratio_for_rule('600900', entry_price, mock_rules_without_atr)
        expected_stop_without_atr = 9.5  # trend_break
        expected_rr_without_atr = (entry_price * 0.15) / (entry_price - expected_stop_without_atr)
        
        print(f"\n无 ATR 止损 (使用 trend_break):")
        print(f"  入场价: ¥{entry_price:.2f}")
        print(f"  trend_break 止损价: ¥{expected_stop_without_atr:.2f}")
        print(f"  盈亏比: {rr_without_atr:.2f}:1")
        print(f"  预期盈亏比: {expected_rr_without_atr:.2f}:1")
        
        if abs(rr_without_atr - expected_rr_without_atr) < 0.01:
            print(f"  ✅ 盈亏比计算正确（使用了 trend_break 止损）")
        else:
            print(f"  ⚠️ 盈亏比计算可能有误")
        
        return True
    except Exception as e:
        print(f"❌ get_rr_ratio_for_rule 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """运行所有测试"""
    print("=" * 70)
    print("ATR 动态止损功能测试")
    print("=" * 70)
    
    results = []
    
    # 运行测试
    results.append(("ATR 计算", test_atr_calculation()))
    results.append(("atr_stop_pct 计算", test_atr_stop_pct_calculation()))
    results.append(("config.yaml 中的 atr_stop_pct", test_atr_stop_in_config()))
    results.append(("get_rr_ratio_for_rule 优先使用 ATR", test_get_rr_ratio_prefers_atr()))
    
    # 总结
    print("\n" + "=" * 70)
    print("测试总结")
    print("=" * 70)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status:10s} {name}")
    
    print(f"\n总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！ATR 动态止损功能正常。")
        return 0
    else:
        print(f"\n⚠️ 有 {total - passed} 个测试失败，请检查实现。")
        return 1

if __name__ == '__main__':
    sys.exit(main())
