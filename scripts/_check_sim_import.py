import sys
sys.path.insert(0, '.')

# 模拟 vqlearn runner 的加载方式
ROOT = __import__('pathlib').Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

print("Python path ROOT:", ROOT)
print("Testing: from vqlearn.strategies.threshold_strategy import ThresholdAlertStrategy")
try:
    from vqlearn.strategies.threshold_strategy import ThresholdAlertStrategy
    print("OK: ThresholdAlertStrategy loaded")
    
    # 检查模块内部 _sim_execute_trade 是否加载成功
    import vqlearn.strategies.threshold_strategy as m
    print("_sim_execute_trade =", m._sim_execute_trade)
    if m._sim_execute_trade is None:
        print("ERROR: _sim_execute_trade is None! sim_executor import failed silently")
        # 手动追查
        try:
            from scripts.sim_executor import execute_trade as _test
            print("Manual import OK, but module-level import failed")
        except Exception as e2:
            print(f"Manual import also failed: {e2}")
    else:
        print("OK: _sim_execute_trade is loaded")
except Exception as e:
    print(f"Failed to load ThresholdAlertStrategy: {e}")
    import traceback; traceback.print_exc()
