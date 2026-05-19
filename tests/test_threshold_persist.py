"""tests/test_threshold_persist.py — 阈值去重持久化测试 (Phase 3)

不依赖 vnpy 引擎，只测 alert_fired SQLite 持久化辅助函数 +
ThresholdAlertStrategy._evaluate 的去重逻辑（用伪 cta_engine）。
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_alert_fired_db_roundtrip():
    """写入 -> 读取 -> 跨日清理"""
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["ALERT_DB_PATH"] = str(Path(tmp) / "alert_fired.db")
        # 必须 reload 模块，让常量重新读环境变量
        import importlib
        import strategies.threshold_alert_strategy as tas
        importlib.reload(tas)

        today = date.today()
        # 写入两条
        tas.record_fire(today, "600330", "stop_loss", 26.5, 27.0, datetime.now())
        tas.record_fire(today, "600330", "stop_loss", 26.4, 27.0, datetime.now())  # 重复，应被 IGNORE
        tas.record_fire(today, "002256", "buy_zone",  4.5, 4.5, datetime.now())

        loaded = tas.load_fired_today(today)
        keys = {(r[0], r[1]) for r in loaded}  # (level, code)
        assert ("stop_loss", "600330") in keys, f"600330 stop_loss 未持久化: {loaded}"
        assert ("buy_zone", "002256") in keys, f"002256 buy_zone 未持久化: {loaded}"
        assert len(loaded) == 2, f"重复行未去重，loaded={loaded}"

        # 老日期 → 应被清理
        old_day = today - timedelta(days=10)
        tas.record_fire(old_day, "999999", "stop_loss", 1.0, 1.0, datetime.now())
        n = tas.cleanup_older_than(today, keep_days=7)
        assert n >= 1, f"清理应删除 1 行，实际 {n}"

        # 重新加载，999999 不应该出现在今天集
        loaded_after = tas.load_fired_today(today)
        assert all(r[1] != "999999" for r in loaded_after)

        print("✅ alert_fired DB roundtrip OK")


def test_strategy_dedup_after_restart():
    """模拟重启：第一次实例化触发一次 → 第二次应该不再 push"""
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["ALERT_DB_PATH"] = str(Path(tmp) / "alert_fired.db")
        # 关闭真实推送
        os.environ["NOTIFIER_DRY_RUN"] = "1"
        import importlib
        import strategies.threshold_alert_strategy as tas
        importlib.reload(tas)
        import notifier.wecom_notifier as wn
        importlib.reload(wn)
        # reload 完之后 push_text 也要重新拿
        from notifier import push_text  # noqa: F401

        # 假 cta_engine：什么都不做，只让 super().__init__ 不炸
        class _FakeEngine:
            def write_log(self, *a, **kw): pass
            def put_strategy_event(self, *a, **kw): pass

        push_count = []
        original_push = tas.push_text

        def _spy_push(text):
            push_count.append(text)
            return True
        tas.push_text = _spy_push

        # ---- 第一次实例 ----
        s1 = tas.ThresholdAlertStrategy(_FakeEngine(), "s1", "600330.SSE", {})
        s1.on_init()
        # 模拟价格跌破 27 触发 stop_loss
        s1._evaluate(26.0, datetime.now())
        first_count = len(push_count)
        assert first_count >= 1, "首次应触发推送"

        # ---- 模拟重启：新建实例 ----
        s2 = tas.ThresholdAlertStrategy(_FakeEngine(), "s2", "600330.SSE", {})
        s2.on_init()  # 应当从 DB 加载已 fired 集
        s2._evaluate(25.5, datetime.now())  # 仍然在跌破区间
        second_count = len(push_count) - first_count
        assert second_count == 0, f"重启后应去重，但又推了 {second_count} 次"

        tas.push_text = original_push
        print(f"✅ 跨进程去重 OK (first={first_count} after_restart={second_count})")


if __name__ == "__main__":
    test_alert_fired_db_roundtrip()
    test_strategy_dedup_after_restart()
    print("\n🎉 Phase 3 tests passed")
