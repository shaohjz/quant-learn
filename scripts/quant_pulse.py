"""scripts/quant_pulse.py — 盘中统一脉搏（提高全项目实时感）

一次跑完「跟你钱相关」的盘中检查：
  1) portfolio_alert   — 真仓/观察股阈值
  2) swing_intraday_watch — 波段机会 + 波段仓止盈止损
  3) 指数快检（上证/沪深300）— 大跌时提一句，不做选股

用法：
  python scripts/quant_pulse.py
  python scripts/quant_pulse.py --force --no-push

建议 schtasks：交易日 09:35–14:50 每 10 分钟（可替代分别挂两个任务，或与之并存）。
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import urllib.request
from datetime import datetime, time as dtime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("quant_pulse")

PY = sys.executable
STATE = ROOT / "output" / "quant_pulse_state.json"


def is_trading_now() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (dtime(9, 30) <= t <= dtime(11, 30)) or (dtime(13, 0) <= t <= dtime(14, 57))


def run_script(rel: str, extra: list[str] | None = None) -> int:
    cmd = [PY, "-u", str(ROOT / rel), *(extra or [])]
    log.info("RUN %s", " ".join(cmd))
    p = subprocess.run(cmd, cwd=str(ROOT))
    return int(p.returncode)


def fetch_index(code: str) -> dict | None:
    """腾讯行情：sh000001 上证 / sh000300 沪深300"""
    try:
        req = urllib.request.Request(
            f"https://qt.gtimg.cn/q={code}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        vals = urllib.request.urlopen(req, timeout=8).read().decode("gbk").split('"')[1].split("~")
        return {
            "name": vals[1],
            "price": float(vals[3] or 0),
            "change_pct": float(vals[32] or 0),
        }
    except Exception as e:
        log.warning("指数失败 %s: %s", code, e)
        return None


def index_pulse(no_push: bool) -> None:
    """大盘异常时提醒一句（同日只推一次）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    state = {"date": today, "index_warned": False}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding="utf-8"))
            if state.get("date") != today:
                state = {"date": today, "index_warned": False}
        except Exception:
            pass

    sh = fetch_index("sh000001")
    hs = fetch_index("sh000300")
    lines = []
    for label, q in (("上证", sh), ("沪深300", hs)):
        if q:
            lines.append(f"{label} {q['price']:.2f} ({q['change_pct']:+.2f}%)")
            log.info("%s %s", label, q)

    if not sh and not hs:
        return

    drop = min(
        [q["change_pct"] for q in (sh, hs) if q],
        default=0,
    )
    summary = " | ".join(lines)
    print(f"[指数] {summary}")

    # 跌超 1.2% 喊一声
    if drop <= -1.2 and not state.get("index_warned"):
        md = (
            f"## 大盘脉冲提醒 {datetime.now().strftime('%H:%M')}\n"
            f"{summary}\n"
            f"> 指数偏弱，抄底单请更谨慎；波段/阈值仍以个股信号为准。"
        )
        if no_push:
            print(md)
        else:
            _push(md)
        state["index_warned"] = True
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _push(md: str) -> bool:
    import yaml
    url = None
    for name in ("config.local.yaml", "config.yaml"):
        p = ROOT / name
        if not p.exists():
            continue
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        url = (data.get("notify") or {}).get("wecom_webhook") or (data.get("notifier") or {}).get("wecom_webhook")
        if url and "YOUR_KEY" not in str(url):
            break
        url = None
    if not url:
        return False
    body = json.dumps({"msgtype": "markdown", "markdown": {"content": md[:2000]}}, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read().decode()).get("errcode") == 0
    except Exception as e:
        log.error("push fail: %s", e)
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--skip-portfolio", action="store_true")
    ap.add_argument("--skip-swing", action="store_true")
    ap.add_argument("--skip-index", action="store_true")
    args = ap.parse_args()

    if not args.force and not is_trading_now():
        log.info("非交易时段，退出")
        print("非交易时段")
        return 0

    extra_push = ["--no-push"] if args.no_push else []
    force = ["--force"] if args.force else []

    rc = 0
    if not args.skip_index:
        try:
            index_pulse(args.no_push)
        except Exception as e:
            log.warning("index_pulse: %s", e)

    if not args.skip_portfolio:
        # portfolio_alert 自己判断时段；force 时仍调用
        r = run_script("scripts/portfolio_alert.py")
        rc = rc or r

    if not args.skip_swing:
        r = run_script("scripts/swing_intraday_watch.py", force + extra_push)
        rc = rc or r

    log.info("quant_pulse done rc=%s", rc)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
