"""
tests/test_fusion_engine.py — 决策器单元测试

跑：
  C:\\Users\\Administrator\\.openclaw\\workspace\\quant-learn\\.venv\\Scripts\\python.exe -m pytest tests/test_fusion_engine.py -v

或不依赖 pytest，直接：
  python tests/test_fusion_engine.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from decision.fusion_engine import decide, Decision


def _signal(action="BUY", confidence=0.8):
    return {"action": action, "confidence": confidence}


def _alert(level="stop_loss", message="x"):
    return {"level": level, "message": message, "trigger": 0, "dir": "below"}


def case_1_stop_loss_overrides_ai_buy():
    """案例 1：止损警报触发，即使 AI 看多也强卖（持仓 5 只之一）"""
    d = decide("002342", current_price=15.74, position_qty=300,
               qlib_signal=_signal("BUY", 0.9),
               threshold_alert=_alert("stop_loss"))
    assert d.action == "SELL"
    assert d.target_account == "real_advisor"   # 002342 持仓
    assert d.qty == 300
    assert d.rule == "STOP_LOSS_OVERRIDE_AI_BUY"
    return "案例1 ✓ 止损强制覆盖 AI BUY"


def case_2_buy_zone_ai_agree():
    """案例 2：观察股进入 buy_zone + AI 看多 → 建仓 qmt_sim"""
    d = decide("002709", current_price=53.00, position_qty=0,
               qlib_signal=_signal("BUY", 0.85),
               threshold_alert=_alert("buy_strong"))
    assert d.action == "BUY"
    assert d.target_account == "qmt_sim"  # 002709 是观察池，不在持仓 5 只
    assert d.qty > 0
    assert d.rule == "BUY_ZONE_AI_AGREE"
    return "案例2 ✓ buy_zone + AI BUY → 建仓 qmt_sim"


def case_3_buy_zone_ai_disagree():
    """案例 3：buy_zone 但 AI 看空 → HOLD"""
    d = decide("002709", current_price=54.00, position_qty=0,
               qlib_signal=_signal("SELL", 0.7),
               threshold_alert=_alert("buy_zone"))
    assert d.action == "HOLD"
    assert d.rule == "BUY_ZONE_AI_DISAGREE"
    return "案例3 ✓ buy_zone + AI SELL → HOLD"


def case_4_qlib_only_high_conf_buy():
    """案例 4：CSI300 内某股，AI 高置信度 BUY，无 alert → 买入到 qmt_sim"""
    d = decide("600519", current_price=1500.00, position_qty=0,
               qlib_signal=_signal("BUY", 0.92),
               threshold_alert=None)
    assert d.action == "BUY"
    assert d.target_account == "qmt_sim"  # 茅台不在持仓 5 只
    assert d.rule == "QLIB_BUY_HIGH_CONF"
    assert d.qty > 0
    return "案例4 ✓ 仅 qlib BUY 高置信度 → qmt_sim 买入"


def case_5_qlib_sell_no_pos():
    """案例 5：AI 看空但无持仓 → HOLD（A 股不开空）"""
    d = decide("000999", current_price=50.0, position_qty=0,
               qlib_signal=_signal("SELL", 0.85),
               threshold_alert=None)
    assert d.action == "HOLD"
    assert d.rule == "QLIB_SELL_NO_POS"
    return "案例5 ✓ AI SELL 无持仓 → HOLD"


def case_6_holding_take_profit_ai_disagree():
    """案例 6：持仓股触发止盈，但 AI 还看多 → HOLD（不止盈）"""
    d = decide("600330", current_price=35.50, position_qty=400,
               qlib_signal=_signal("BUY", 0.7),
               threshold_alert=_alert("take_profit"))
    assert d.action == "HOLD"
    assert d.target_account == "real_advisor"  # 600330 持仓
    assert d.rule == "TP_AI_DISAGREE"
    return "案例6 ✓ 持仓止盈 + AI BUY → HOLD（暂不止盈）"


def case_7_holding_take_profit_ai_agree():
    """案例 7：持仓股止盈 + AI 看空 → 清仓"""
    d = decide("600330", current_price=35.50, position_qty=400,
               qlib_signal=_signal("SELL", 0.85),
               threshold_alert=_alert("take_profit"))
    assert d.action == "SELL"
    assert d.qty == 400
    assert d.rule == "TAKE_PROFIT_AI_AGREE"
    return "案例7 ✓ 持仓止盈 + AI SELL → 清仓"


def case_8_no_qlib_no_alert():
    """案例 8：啥都没 → HOLD"""
    d = decide("000001", current_price=10.0, position_qty=0,
               qlib_signal=None, threshold_alert=None)
    assert d.action == "HOLD"
    assert d.rule == "DEFAULT_HOLD"
    return "案例8 ✓ 无信号 → DEFAULT_HOLD"


def case_9_qlib_buy_low_conf():
    """案例 9：AI BUY 但置信度低 → HOLD"""
    d = decide("600519", current_price=1500.0, position_qty=0,
               qlib_signal=_signal("BUY", 0.5),
               threshold_alert=None)
    assert d.action == "HOLD"
    assert d.rule == "QLIB_BUY_LOW_CONF"
    return "案例9 ✓ AI BUY 低置信度 → HOLD"


def case_10_holding_stop_loss_no_qlib():
    """案例 10：持仓股止损，没 qlib 信号也强卖（老规则）"""
    d = decide("002453", current_price=5.79, position_qty=300,
               qlib_signal=None,
               threshold_alert=_alert("stop_loss"))
    assert d.action == "SELL"
    assert d.qty == 300
    assert d.target_account == "real_advisor"
    assert d.rule == "STOP_LOSS"
    return "案例10 ✓ 持仓股止损 + 无 qlib → 强卖（老规则）"


CASES = [case_1_stop_loss_overrides_ai_buy, case_2_buy_zone_ai_agree,
         case_3_buy_zone_ai_disagree, case_4_qlib_only_high_conf_buy,
         case_5_qlib_sell_no_pos, case_6_holding_take_profit_ai_disagree,
         case_7_holding_take_profit_ai_agree, case_8_no_qlib_no_alert,
         case_9_qlib_buy_low_conf, case_10_holding_stop_loss_no_qlib]


def main():
    print("=" * 70)
    print(f"fusion_engine 测试，共 {len(CASES)} 个案例")
    print("=" * 70)
    pass_n = 0
    fail = []
    for i, c in enumerate(CASES, 1):
        try:
            msg = c()
            print(f"  [{i:>2}/{len(CASES)}] {msg}")
            pass_n += 1
        except AssertionError as e:
            print(f"  [{i:>2}/{len(CASES)}] ❌ {c.__name__} FAILED: {e}")
            fail.append(c.__name__)
        except Exception as e:
            print(f"  [{i:>2}/{len(CASES)}] ⚠️ {c.__name__} ERROR: {e}")
            fail.append(c.__name__)
    print("=" * 70)
    print(f"通过 {pass_n}/{len(CASES)}" + ("" if not fail else f"  失败：{fail}"))
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
