"""scripts/scanner_with_fallback.py — Scanner 二段式调用器

策略：
1. 先尝试 morning_scanner（全市场 800+ 股，依赖 AKShare）
2. 如果在 90 秒内没出结果或出错，fallback 到 scanner_lite（30 股，新浪+baostock）

这是给 cron 用的健壮版入口。
背景：AKShare 在云桌面（21.214.59.210）被东财限流，2026-05-24 起失败率 100%。
"""
from __future__ import annotations
import sys, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

PRIMARY = ROOT / "scripts" / "morning_scanner.py"
FALLBACK = ROOT / "scripts" / "scanner_lite.py"
TIMEOUT_PRIMARY = 120  # 秒


def try_primary() -> bool:
    print(f"[scanner-fallback] 1/2 尝试主路径 morning_scanner.py（超时 {TIMEOUT_PRIMARY}s）", flush=True)
    try:
        p = subprocess.run(
            [PY, "-u", str(PRIMARY)],
            timeout=TIMEOUT_PRIMARY,
            cwd=str(ROOT),
        )
        return p.returncode == 0
    except subprocess.TimeoutExpired:
        print("[scanner-fallback] ⏰ 主路径超时（多半是 AKShare 卡住），切 fallback", flush=True)
        return False
    except Exception as e:
        print(f"[scanner-fallback] ❌ 主路径异常: {e}", flush=True)
        return False


def try_fallback() -> bool:
    print(f"[scanner-fallback] 2/2 跑降级版 scanner_lite.py", flush=True)
    p = subprocess.run(
        [PY, "-u", str(FALLBACK), "--top", "15"],
        cwd=str(ROOT),
    )
    return p.returncode == 0


def main():
    t0 = time.time()
    if try_primary():
        print(f"[scanner-fallback] ✅ 主路径成功，用时 {time.time()-t0:.1f}s", flush=True)
        sys.exit(0)
    if try_fallback():
        print(f"[scanner-fallback] ✅ 降级路径成功，用时 {time.time()-t0:.1f}s", flush=True)
        sys.exit(0)
    print(f"[scanner-fallback] ❌ 两条路径都失败，用时 {time.time()-t0:.1f}s", flush=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
