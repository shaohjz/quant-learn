"""
scripts/run_fusion_dispatch.py — 双账户分流执行器

流程：
  1. 加载 daily_signals.json（CSI300 全量）
  2. 加载 alert_state.json（portfolio_alert 当日触发的阈值）
  3. 拉当前价格（仅对涉及到的股票）
  4. 对每个 (股票, 信号) 调 fusion_engine.decide()
  5. 分流执行：
     - target=qmt_sim       → 推到 QMT 模拟账户（dry_run 模式只 print）
     - target=real_advisor  → 仅推送企微（注意：dry-run 期间不真发，只 print）
  6. 限制：QMT 操作每天最多 20 条，按 confidence 排序

⚠️ Dry-run 模式（默认）：
   - 不真连 QMT
   - 不真发企微（除非 --send 显式打开）
   - 输出到 output/fusion_dispatch_<date>.log

用法：
  python scripts/run_fusion_dispatch.py                # dry-run 默认
  python scripts/run_fusion_dispatch.py --send         # 真发企微（仅持仓 5 只建议）
  python scripts/run_fusion_dispatch.py --no-broker    # 跳过 QMT 创建（纯 print）
"""
from __future__ import annotations
import sys, json, argparse, traceback, urllib.request, io
from pathlib import Path
from datetime import datetime, date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows 控制台 utf-8
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import yaml

from decision.fusion_engine import decide, Decision, HOLDINGS
from sim.realtime_price import get_latest_prices

DAILY_SIGNALS = ROOT / "data" / "daily_signals.json"
ALERT_STATE = ROOT / "output" / "alert_state.json"
DISPATCH_LOG_DIR = ROOT / "output"
DISPATCH_LOG_DIR.mkdir(exist_ok=True)

QMT_DAILY_MAX = 20  # QMT 每日操作上限


# ---------------- 配置加载 ----------------
def load_cfg() -> dict:
    p = ROOT / "config.local.yaml"
    if p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}


def get_webhook(cfg: dict) -> str | None:
    return ((cfg.get("notifier") or {}).get("wecom_webhook")) or None


# ---------------- 输入加载 ----------------
def load_signals() -> dict:
    if not DAILY_SIGNALS.exists():
        return {}
    return json.loads(DAILY_SIGNALS.read_text(encoding="utf-8"))


def load_today_alerts(today: str) -> dict:
    """从 alert_state.json 读取今天触发的阈值。
    返回 { rule_id: { triggered_at, price, trigger } }"""
    if not ALERT_STATE.exists():
        return {}
    data = json.loads(ALERT_STATE.read_text(encoding="utf-8"))
    return data.get(today, {})


def merge_alert_rules(today_alerts: dict) -> dict:
    """把 alert_state.json 的 rule_id (code_level) 解出 code 和 level，
    按 code 分组返回 { code: [ {level, triggered_at, price, trigger}, ... ] }"""
    by_code: dict = {}
    for rule_id, info in today_alerts.items():
        if "_" not in rule_id:
            continue
        code, level = rule_id.split("_", 1)
        by_code.setdefault(code, []).append({
            "level": level,
            "triggered_at": info.get("triggered_at"),
            "price": info.get("price"),
            "trigger": info.get("trigger"),
        })
    return by_code


def pick_priority_alert(alerts: list) -> dict | None:
    """同股有多条触发时优先级（高 → 低）：
       hard_stop > stop_loss* > deep_drop > limitdown* > take_profit > half_out > buy_strong > buy_zone > 其它
    """
    if not alerts:
        return None
    priority = [
        "hard_stop", "stop_loss", "stop_loss_tight", "deep_drop",
        "limitdown_open", "rebound_exit", "trend_break",
        "take_profit", "take_profit_half", "half_out", "yc_exit",
        "buy_strong", "buy_zone",
    ]
    rank = {l: i for i, l in enumerate(priority)}
    return sorted(alerts, key=lambda a: rank.get(a["level"], 999))[0]


# ---------------- 推送 ----------------
def push_webhook(content: str, webhook: str | None, dry_run: bool = True) -> bool:
    if dry_run or not webhook:
        print(f"[WEBHOOK-DRY-RUN] (len={len(content)}) {content[:120]}{'...' if len(content)>120 else ''}",
              flush=True)
        return False
    try:
        body = json.dumps({"msgtype": "text", "text": {"content": content}}).encode("utf-8")
        req = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
        return '"errcode":0' in resp
    except Exception as e:
        print(f"[WEBHOOK-FAIL] {e}", flush=True)
        return False


# ---------------- 主流程 ----------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true",
                        help="真发企微（默认 dry-run 不发）")
    parser.add_argument("--no-broker", action="store_true",
                        help="跳过 QMT broker 创建，仅 print")
    parser.add_argument("--max-qmt", type=int, default=QMT_DAILY_MAX)
    args = parser.parse_args()

    cfg = load_cfg()
    broker_cfg = cfg.get("broker") or {}
    live_cfg = broker_cfg.get("live") or {}
    webhook = get_webhook(cfg)
    today = date.today().isoformat()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("=" * 76)
    print(f"run_fusion_dispatch  @ {now_str}")
    print(f"  daily_signals      : {DAILY_SIGNALS}")
    print(f"  alert_state        : {ALERT_STATE}")
    print(f"  webhook real-send  : {args.send}")
    print(f"  no-broker          : {args.no_broker}")
    print("=" * 76)

    sig_doc = load_signals()
    if not sig_doc:
        print("⚠ daily_signals.json 不存在或为空，退出")
        return 1
    schema = sig_doc.get("schema_version")
    print(f"  signals.schema     : v{schema}, model={sig_doc.get('model')}, "
          f"trading_date={sig_doc.get('trading_date')}, n={len(sig_doc.get('signals',[]))}")
    qlib_by_code = {s["code"]: s for s in sig_doc.get("signals", [])}

    alerts_today = load_today_alerts(today)
    alerts_by_code = merge_alert_rules(alerts_today)
    print(f"  today alerts       : {len(alerts_today)} 条 → {len(alerts_by_code)} 只股票触发")

    # ------------- 收集所有候选股 -------------
    candidate_codes: set[str] = set()
    candidate_codes.update(qlib_by_code.keys())
    candidate_codes.update(alerts_by_code.keys())
    candidate_codes.update(HOLDINGS)

    # ------------- 拉价 -------------
    print(f"\n[1/4] 拉取 {len(candidate_codes)} 只股票现价 ...", flush=True)
    try:
        # 限制：避免单次新浪请求过大，分批
        prices = {}
        codes_list = sorted(candidate_codes)
        for i in range(0, len(codes_list), 60):
            chunk = codes_list[i:i+60]
            prices.update(get_latest_prices(chunk))
        print(f"  ↳ 拿到价格 {len(prices)} 条")
    except Exception:
        print("  ⚠ 拉价失败，继续用 0 占位")
        traceback.print_exc()
        prices = {}

    # ------------- 持仓查询（dry-run 走空仓） -------------
    print(f"\n[2/4] 查询 QMT 模拟账户持仓 ...", flush=True)
    pos_qty_by_code: dict[str, int] = {}  # 默认 0
    qmt_account_id = live_cfg.get("qmt_account", "")
    qmt_dry = bool(live_cfg.get("dry_run", True))
    if not args.no_broker:
        try:
            from broker.factory import get_broker
            qmt_broker = get_broker(
                mode="live",
                qmt_path=live_cfg.get("qmt_path"),
                qmt_account=qmt_account_id,
                session_id=int(live_cfg.get("session_id", 970515)),
                dry_run=qmt_dry,
                xtquant_site_packages=live_cfg.get("xtquant_site_packages"),
            )
            for p in qmt_broker.get_positions():
                pos_qty_by_code[p.stock_code.replace("SH", "").replace("SZ", "").replace(".", "")] = p.quantity
            qmt_broker.disconnect()
            print(f"  ↳ QMT 持仓 {len(pos_qty_by_code)} 只（dry_run={qmt_dry}）")
        except Exception:
            print("  ⚠ QMT broker 初始化失败，把所有持仓视为 0")
            traceback.print_exc()

    # 真实账户持仓（来自 USER 输入）：用于做"AI 给真实账户的建议"
    REAL_HOLDINGS_QTY = {
        "600330": 600,    # 估算（之前规则提到 400~600）
        "002256": 700,
        "002453": 300,
        "002342": 100,    # 5/19 已跌停剩 100
        "603601": 100,    # 5/19 当天买入
    }

    # ------------- 跑 fusion_engine -------------
    print(f"\n[3/4] 运行 fusion_engine 决策 ...", flush=True)
    decisions: list[Decision] = []
    for code in sorted(candidate_codes):
        qsig = qlib_by_code.get(code)
        alerts = alerts_by_code.get(code) or []
        alert = pick_priority_alert(alerts)

        # 现价：优先 alert 报告的 price，再 prices，再 qlib 没有就 0
        cur = 0.0
        if alert and alert.get("price"):
            cur = float(alert["price"])
        elif code in prices and prices[code].get("price"):
            cur = float(prices[code]["price"])

        # 持仓：持仓 5 只走 REAL_HOLDINGS_QTY；其它走 QMT 实查
        if code in HOLDINGS:
            position_qty = REAL_HOLDINGS_QTY.get(code, 0)
        else:
            position_qty = pos_qty_by_code.get(code, 0)

        d = decide(stock_code=code, current_price=cur,
                   position_qty=position_qty,
                   qlib_signal=qsig, threshold_alert=alert)
        decisions.append(d)

    actionable = [d for d in decisions if d.is_actionable()]
    print(f"  ↳ 决策完成: total={len(decisions)} actionable={len(actionable)}")

    # ------------- 分流 -------------
    print(f"\n[4/4] 分流到 QMT 模拟 / 真实账户建议 ...", flush=True)
    qmt_decisions = [d for d in actionable if d.target_account == "qmt_sim"]
    advisor_decisions = [d for d in actionable if d.target_account == "real_advisor"]

    # QMT 限额：取 conf top-N
    qmt_decisions.sort(key=lambda d: d.confidence, reverse=True)
    qmt_to_run = qmt_decisions[:args.max_qmt]
    qmt_dropped = qmt_decisions[args.max_qmt:]

    # ------------- 执行 QMT（dry-run 不真下单） -------------
    print(f"\n----- [QMT 模拟账户] 推 {len(qmt_to_run)} / {len(qmt_decisions)} 条（限额 {args.max_qmt}） -----")
    qmt_results = []
    qmt_broker = None
    if qmt_to_run and not args.no_broker:
        try:
            from broker.factory import get_broker
            qmt_broker = get_broker(
                mode="live",
                qmt_path=live_cfg.get("qmt_path"),
                qmt_account=qmt_account_id,
                session_id=int(live_cfg.get("session_id", 970515)),
                dry_run=qmt_dry,
                xtquant_site_packages=live_cfg.get("xtquant_site_packages"),
            )
        except Exception:
            print("  ⚠ QMT broker 二次初始化失败，本轮所有 QMT 决策跳过")
            traceback.print_exc()
            qmt_broker = None

    for i, d in enumerate(qmt_to_run, 1):
        line = (f"  [{i:>2}] {d.action:>4}  {d.stock_code}  qty={d.qty:>4}  "
                f"price={d.price:.2f}  conf={d.confidence:.2f}  rule={d.rule}  "
                f"reason={d.reason}")
        print(line)
        if qmt_broker is None:
            qmt_results.append({"decision": d.__dict__, "skipped": "no broker"})
            continue
        import datetime as _dt, json as _json
        # REQ-032: 构造 signal_detail
        _now = _dt.datetime.now().isoformat(timespec='seconds')
        _triggered = []
        if d.rule:
            _triggered.append({"rule": d.rule, "indicator": d.rule,
                                  "current_value": d.price, "threshold": None, "operator": "=="})
        if d.confidence:
            _triggered.append({"rule": "confidence", "indicator": "ai_confidence",
                                  "current_value": d.confidence, "threshold": 0.5, "operator": ">="})
        _detail = {
            "signal": d.action,
            "trigger_type": "fusion_engine",
            "triggered_rules": _triggered,
            "indicators_snapshot": {"price": round(d.price, 4) if d.price else None, "confidence": d.confidence},
            "strategy_version": "fusion_engine.py/v1.0",
            "price_snapshot": {"close": round(d.price, 4) if d.price else None},
            "timestamp": _now,
        }
        try:
            if d.action == "BUY":
                r = qmt_broker.buy(d.stock_code, d.price, d.qty,
                                   stock_name=str((qlib_by_code.get(d.stock_code) or {}).get("name","")),
                                   signal_reason=d.reason, trade_date=date.today(),
                                   signal_detail=_detail)
            else:
                r = qmt_broker.sell(d.stock_code, d.price, d.qty,
                                    stock_name=str((qlib_by_code.get(d.stock_code) or {}).get("name","")),
                                    signal_reason=d.reason, trade_date=date.today(),
                                    signal_detail=_detail)
            qmt_results.append({"decision": d.__dict__, "order": {
                "success": r.success, "order_id": r.order_id, "msg": r.msg, "extra": r.extra
            }})
            print(f"        → success={r.success} order_id={r.order_id} msg={r.msg}")
        except Exception:
            traceback.print_exc()
            qmt_results.append({"decision": d.__dict__, "error": traceback.format_exc()})

    if qmt_broker is not None:
        qmt_broker.disconnect()

    if qmt_dropped:
        print(f"\n  超过 {args.max_qmt} 条上限，丢弃 {len(qmt_dropped)} 条（按 conf 倒序保留 top）：")
        for d in qmt_dropped[:5]:
            print(f"    - {d.stock_code} {d.action} conf={d.confidence:.2f} {d.rule}")

    # ------------- 真实账户建议（仅推送 5 持仓相关） -------------
    print(f"\n----- [真实账户建议] 仅推送 {len(advisor_decisions)} 条（持仓 5 只） -----")
    advisor_lines = []
    for i, d in enumerate(advisor_decisions, 1):
        name = (qlib_by_code.get(d.stock_code) or {}).get("name", "")
        line = (f"  [{i}] {d.action} {d.stock_code} {name} qty={d.qty} "
                f"price={d.price:.2f} conf={d.confidence:.2f} rule={d.rule}")
        print(line)
        print(f"      reason: {d.reason}")
        advisor_lines.append(
            f"• {d.action} {d.stock_code} {name}\n"
            f"  数量={d.qty}, 现价={d.price:.2f}, 置信度={d.confidence:.2f}\n"
            f"  规则={d.rule}\n  说明={d.reason}"
        )

    # 推送企微（dry-run 不真发）
    pushed = False
    if advisor_decisions:
        body = (
            f"📊 AI 给真实账户的建议（{today} {now_str.split()[1]}）\n"
            + "—" * 32 + "\n"
            + "\n".join(advisor_lines)
            + f"\n\n（持仓 5 只仅作建议，不会自动下单；QMT 模拟账户已尝试 {len(qmt_to_run)} 条决策，dry_run={qmt_dry}）"
        )
        ok = push_webhook(body, webhook, dry_run=not args.send)
        pushed = ok
        print(f"\n企微推送：{'✅ 已发送' if ok else '🟡 dry-run / 未发送'}")
    else:
        print("\n（无对真实账户的建议，跳过推送）")

    # ------------- 落地日志 -------------
    log = {
        "ts": now_str,
        "trading_date": today,
        "qmt_dry_run": qmt_dry,
        "send_webhook": args.send,
        "pushed": pushed,
        "schema_version": schema,
        "model": sig_doc.get("model"),
        "qmt_decisions": [d.__dict__ for d in qmt_to_run],
        "qmt_dropped": [d.__dict__ for d in qmt_dropped],
        "advisor_decisions": [d.__dict__ for d in advisor_decisions],
        "qmt_results": qmt_results,
    }
    log_path = DISPATCH_LOG_DIR / f"fusion_dispatch_{today}.json"
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n📄 dispatch 日志 -> {log_path}")
    print("=" * 76)

    return 0


if __name__ == "__main__":
    sys.exit(main())
