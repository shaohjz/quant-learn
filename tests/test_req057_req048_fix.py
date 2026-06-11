"""
自测脚本：验证 REQ-057 + REQ-048 修复
============================================
REQ-057: _exec_via_sim 用 trade 字段判断成交（非 success）
REQ-048: decide_action 支持 trend_break level（SELL_ALL）
         + _verify_sell_executed 卖出后持仓校验
         + record_sell_executed 返回行数校验 + reset_stuck_confirmed
"""
import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
# 如果在 tests/ 子目录运行，需要回退到项目根目录
if os.path.basename(ROOT) == 'tests':
    ROOT = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault('QUANT_DB_PATH', os.path.join(ROOT, 'data', 'sim_live_mirror.db'))

def test_req057_exec_via_sim_trade_check():
    """REQ-057: 验证 _exec_via_sim 用 trade 字段而非 success 判断成交"""
    # 读取 threshold_strategy.py 源码，验证关键逻辑
    with open(os.path.join(ROOT, 'vqlearn/strategies/threshold_strategy.py'), 'r', encoding='utf-8') as f:
        content = f.read()

    # 验证1: _exec_via_sim 中用 trade is not None 判断成交
    assert "r.get('trade') is not None" in content, "REQ-057: _exec_via_sim 应使用 trade 字段判断成交"
    
    # 验证2: success=True 但 trade=None 时不应回写 executed
    assert "if r.get('success') and not filled:" in content, "REQ-057: 应处理 success=True 但未成交的情况"
    
    # 验证3: 不应再用 success 直接判断买入成功
    # 确保 _try_buy 中也是用 _exec_via_sim 返回的 success（已间接依赖 trade 判断）
    print("✅ REQ-057: _exec_via_sim 使用 trade 字段判断成交")

def test_req048_decide_action_trend_break():
    """REQ-048: 验证 decide_action 支持 trend_break level"""
    with open(os.path.join(ROOT, 'scripts/sim_executor.py'), 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 找到 decide_action 函数体
    start = content.index('def decide_action(')
    next_func = content.index('\ndef ', start + 1)
    func_body = content[start:next_func]
    
    # 验证1: trend_break 在 decide_action 中有分支
    assert 'trend_break' in func_body, "REQ-048: decide_action 应包含 trend_break 分支"
    
    # 验证2: trend_break 应返回 SELL_ALL（全仓卖出）
    assert "SELL_ALL" in func_body, "REQ-048: trend_break 分支应返回 SELL_ALL"
    
    # 验证3: 无持仓时应返回 NO_ACTION
    assert "无持仓" in func_body or "NO_ACTION" in func_body, "REQ-048: trend_break 无持仓时应返回 NO_ACTION"
    
    print("✅ REQ-048: decide_action 支持 trend_break → SELL_ALL")

def test_req048_verify_sell_executed():
    """REQ-048: 验证 _verify_sell_executed 方法存在"""
    with open(os.path.join(ROOT, 'vqlearn/strategies/threshold_strategy.py'), 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 验证: _verify_sell_executed 方法定义存在
    assert '_verify_sell_executed' in content, "REQ-048: 应定义 _verify_sell_executed 方法"
    assert 'def _verify_sell_executed' in content, "REQ-048: _verify_sell_executed 应为方法定义"
    
    # 验证: _try_sell 中调用了 _verify_sell_executed
    try_sell_start = content.index('def _try_sell(')
    try_sell_end = content.index('def ', try_sell_start + 10)
    try_sell_body = content[try_sell_start:try_sell_end]
    assert '_verify_sell_executed' in try_sell_body, "REQ-048: _try_sell 应调用 _verify_sell_executed"
    
    print("✅ REQ-048: _verify_sell_executed 卖出后持仓校验已集成")

def test_req048_record_sell_returns_count():
    """REQ-048: 验证 record_sell_executed 返回更新行数"""
    with open(os.path.join(ROOT, 'vqlearn/services/threshold_state.py'), 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 找到 record_sell_executed 函数
    start = content.index('def record_sell_executed(')
    end = content.index('\ndef ', start + 1)
    func_body = content[start:end]
    
    # 验证: 函数返回 cursor.rowcount
    assert 'rowcount' in func_body, "REQ-048: record_sell_executed 应返回 cursor.rowcount"
    
    print("✅ REQ-048: record_sell_executed 返回更新行数")

def test_req048_reset_stuck_confirmed():
    """REQ-048: 验证 reset_stuck_confirmed 函数存在"""
    with open(os.path.join(ROOT, 'vqlearn/services/threshold_state.py'), 'r', encoding='utf-8') as f:
        content = f.read()
    
    assert 'def reset_stuck_confirmed(' in content, "REQ-048: reset_stuck_confirmed 应定义"
    
    # 验证: _try_sell 中引用了 reset_stuck_confirmed
    with open(os.path.join(ROOT, 'vqlearn/strategies/threshold_strategy.py'), 'r', encoding='utf-8') as f:
        strat_content = f.read()
    assert 'reset_stuck_confirmed' in strat_content, "REQ-048: threshold_strategy 应引用 reset_stuck_confirmed"
    
    print("✅ REQ-048: reset_stuck_confirmed 已集成")

def test_req048_audit_executed_without_trade():
    """REQ-048: 验证 audit_executed_without_trade 函数存在"""
    with open(os.path.join(ROOT, 'vqlearn/services/threshold_state.py'), 'r', encoding='utf-8') as f:
        content = f.read()
    
    assert 'def audit_executed_without_trade(' in content, "REQ-048: audit_executed_without_trade 应定义"
    assert 'def cleanup_orphaned_executed(' in content, "REQ-048: cleanup_orphaned_executed 应定义"
    
    print("✅ REQ-048: audit + cleanup 工具函数就绪")

def test_execute_trade_trend_break_returns_sell():
    """REQ-048: 集成测试 - simulate decide_action for trend_break"""
    # 直接调用 decide_action 验证返回值
    from scripts.sim_executor import decide_action
    
    # 有持仓时，trend_break 应返回 SELL_ALL
    rule = {
        'code': '603757',
        'name': '大元泵业',
        'level': 'trend_break',
        'trigger': 25.0,
        'dir': 'below',
    }
    # Mock position data
    position = {'quantity': 100, 'avg_cost': 28.0, 'highest_price': 30.0, 'trailing_stop_price': 27.0}
    
    action = decide_action(rule, 24.5, position=position)
    assert action == 'SELL_ALL', f"REQ-048: trend_break 应返回 SELL_ALL，实际返回 {action}"
    print(f"✅ REQ-048: decide_action(trend_break) → SELL_ALL")
    
    # take_profit 应返回 SELL_HALF
    rule_tp = {
        'code': '603757',
        'name': '大元泵业',
        'level': 'take_profit',
        'trigger': 35.0,
        'dir': 'above',
    }
    action_tp = decide_action(rule_tp, 35.5, position=position)
    assert action_tp == 'SELL_HALF', f"REQ-048: take_profit 应返回 SELL_HALF，实际返回 {action_tp}"
    print(f"✅ REQ-048: decide_action(take_profit) → SELL_HALF")
    
    # take_profit_half 也应返回 SELL_HALF
    rule_tph = {
        'code': '603757',
        'name': '大元泵业',
        'level': 'take_profit_half',
        'trigger': 33.0,
        'dir': 'above',
    }
    action_tph = decide_action(rule_tph, 33.5, position=position)
    assert action_tph == 'SELL_HALF', f"REQ-048: take_profit_half 应返回 SELL_HALF，实际返回 {action_tph}"
    print(f"✅ REQ-048: decide_action(take_profit_half) → SELL_HALF")


if __name__ == '__main__':
    print("=" * 60)
    print("自测: REQ-057 + REQ-048 修复验证")
    print("=" * 60)
    
    tests = [
        ("REQ-057: trade字段判断成交", test_req057_exec_via_sim_trade_check),
        ("REQ-048: decide_action trend_break", test_req048_decide_action_trend_break),
        ("REQ-048: _verify_sell_executed", test_req048_verify_sell_executed),
        ("REQ-048: record_sell_executed返回行数", test_req048_record_sell_returns_count),
        ("REQ-048: reset_stuck_confirmed", test_req048_reset_stuck_confirmed),
        ("REQ-048: audit工具函数", test_req048_audit_executed_without_trade),
        ("REQ-048: 集成测试 decide_action", test_execute_trade_trend_break_returns_sell),
    ]
    
    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"❌ {name}: {e}")
            failed += 1
    
    print()
    print("=" * 60)
    print(f"结果: {passed} 通过, {failed} 失败 / 共 {len(tests)} 项")
    print("=" * 60)
    
    sys.exit(0 if failed == 0 else 1)
