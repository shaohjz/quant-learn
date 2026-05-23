"""
scripts/portfolio_alert.py — 盘中阈值提醒（持仓 + 观察股）

策略：
  - 价格触发阈值 → 推消息
  - 同一阈值同一天只推一次（用 alert_state.json 去重）
  - 非交易时段直接退出
  - 调用方（cron）拿 stdout 推给用户；没触发就只有"无新警报"一行

阈值表说明：
  level: 行动等级（stop_loss/half_out/take_profit/buy_zone/...）
  trigger_dir: 'below'=价格跌至该值或以下触发；'above'=涨至该值或以上触发
  message: 推消息正文

日志输出：
  - output/portfolio_alert.log  ：每次运行的详细日志（追加写）
  - output/intraday_log.jsonl   ：每次现价快照 JSON（一行一条，便于后续分析）
  - output/alert_state.json     ：今日已触发阈值去重记录
"""
import json, sys, logging, traceback
import json, sys, logging, traceback, urllib.request, io
from datetime import datetime, time as dtime
from pathlib import Path

# 强制 stdout/stderr 使用 UTF-8（避免 Windows 计划任务下 GBK 编码 emoji 崩溃）
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.realtime_price import get_latest_prices

OUTPUT_DIR = ROOT / "output"
STATE_FILE = OUTPUT_DIR / "alert_state.json"
LOG_FILE = OUTPUT_DIR / "portfolio_alert.log"
INTRADAY_LOG = OUTPUT_DIR / "intraday_log.jsonl"
OUTPUT_DIR.mkdir(exist_ok=True)

# ====================================================================
#  Webhook 推送配置
# ====================================================================
def _load_webhook():
    """从 config.local.yaml 读 webhook URL，读不到返回 None"""
    try:
        import yaml
        local_cfg = ROOT / "config.local.yaml"
        if local_cfg.exists():
            data = yaml.safe_load(local_cfg.read_text(encoding="utf-8")) or {}
            return (data.get("notifier") or {}).get("wecom_webhook")
    except Exception:
        pass
    return None

WEBHOOK_URL = _load_webhook()

def push_webhook(content: str) -> bool:
    """推送一条文本到企微群机器人，失败不报错仅记志"""
    if not WEBHOOK_URL:
        return False
    try:
        body = json.dumps({"msgtype": "text", "text": {"content": content}}).encode("utf-8")
        req = urllib.request.Request(WEBHOOK_URL, data=body,
                                     headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
        ok = '"errcode":0' in resp
        if ok:
            logger.info(f"webhook 推送成功")
        else:
            logger.warning(f"webhook 返回异常: {resp}")
        return ok
    except Exception as e:
        logger.error(f"webhook 推送失败: {e}")
        return False

# ====================================================================
#  日志配置
# ====================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),  # 控制台 stderr不干扰 stdout 传递给 cron
    ],
)
logger = logging.getLogger("portfolio_alert")

# ====================================================================
#  阈值规则表（行动手册）
# ====================================================================
#  阈值规则表（2026-05-22 重构：从 config.yaml + sim_live_mirror.db 加载）
#
#  以前这里是硬编码 RULES 列表，现在由 sim/portfolio.py 统一供应：
#    - 持仓股规则 ← config.yaml: real_portfolio_rules
#    - 观察股规则 ← config.yaml: watchlist
#    - 持仓数量/成本 ← sim_live_mirror.db (account_id=2 真实账户)
#
#  修改规则请改 config.yaml 。
# ====================================================================
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from sim.portfolio import load_all_alert_rules  # noqa: E402
RULES = load_all_alert_rules()


def in_trade_hours(now: datetime) -> bool:
    """A股交易时段：周一到周五 9:30-11:30 / 13:00-15:00"""
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (dtime(9, 30) <= t <= dtime(11, 30)) or (dtime(13, 0) <= t <= dtime(15, 0))


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def is_triggered(price: float, trigger: float, direction: str) -> bool:
    if direction == "below":
        return price <= trigger
    else:  # above
        return price >= trigger


def main():
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    run_id = now.strftime("%H%M%S")
    
    logger.info(f"==== 运行开始 run_id={run_id} ====")
    
    if not in_trade_hours(now):
        # 非交易时段，静默退出
        msg = f"📴 非交易时段 ({now.strftime('%Y-%m-%d %H:%M %A')})，跳过"
        print(msg)
        logger.info("非交易时段，退出")
        return 0

    # 拉取所有股票当前价
    codes = list({r["code"] for r in RULES})
    logger.info(f"准备拉取 {len(codes)} 只股票行情: {codes}")
    try:
        prices = get_latest_prices(codes)
        logger.info(f"行情拉取成功，返回 {len(prices)} 条")
    except Exception as e:
        logger.error(f"获取行情失败: {e}\n{traceback.format_exc()}")
        print(f"❌ 获取行情失败: {e}")
        return 1

    # 提取干净价格（price 字段）
    clean_prices = {}
    for c, p in prices.items():
        if isinstance(p, dict):
            v = p.get("price") or p.get("close") or 0
        else:
            v = p or 0
        clean_prices[c] = float(v) if v else 0

    # 写快照 JSONL（便于后续分析价格走势）
    snapshot = {
        "ts": now.isoformat(),
        "run_id": run_id,
        "prices": clean_prices,
    }
    try:
        with open(INTRADAY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"写快照失败: {e}")

    # 加载已推送状态
    state = load_state()
    today_state = state.get(today, {})
    logger.info(f"今日已推送阈值数: {len(today_state)}")

    triggered_msgs = []
    checked_count = 0
    skipped_already = 0
    
    for rule in RULES:
        code = rule["code"]
        rule_id = f"{code}_{rule['level']}"
        
        # 已推过，跳过
        if today_state.get(rule_id):
            skipped_already += 1
            continue
        
        cur_price = clean_prices.get(code, 0)
        if cur_price <= 0:
            logger.warning(f"跳过 {code}: 价格为 0或缺失")
            continue
        
        checked_count += 1
        
        if is_triggered(cur_price, rule["trigger"], rule["dir"]):
            arrow = "↓" if rule["dir"] == "below" else "↑"
            msg = (f"【{rule['name']} {code}】\n"
                   f"现价 ¥{cur_price:.2f} {arrow} 阈值 ¥{rule['trigger']:.2f}\n"
                   f"{rule['message']}")
            
            # 虚拟下单（全自动模式 A）
            try:
                from sim_executor import execute_trade
                trade_result = execute_trade(rule, cur_price)
                if trade_result['success'] and trade_result['action'] != 'NO_ACTION':
                    msg += f"\n🤖 虚拟交易: {trade_result['message']}"
                    logger.warning(f"🤖 虚拟交易: {rule_id} → {trade_result['message']}")
                elif not trade_result['success']:
                    msg += f"\n⚠️ 虚拟下单失败: {trade_result['message']}"
            except Exception as ex:
                logger.warning(f"虚拟下单异常: {ex}")
            
            triggered_msgs.append(msg)
            today_state[rule_id] = {
                "triggered_at": now.strftime("%H:%M"),
                "price": cur_price,
                "trigger": rule["trigger"],
            }
            logger.warning(f"🔔 触发阈值: {rule_id} 价={cur_price} 阈值={rule['trigger']} {rule['dir']}")

    # 保存状态
    state[today] = today_state
    # 清理 7 天前的状态
    keep_days = 7
    sorted_dates = sorted(state.keys(), reverse=True)
    state = {d: state[d] for d in sorted_dates[:keep_days]}
    save_state(state)

    # 运行后更新所有持仓的市值（使 sim_account total_value 反映现价）
    try:
        from sim_executor import update_all_positions_market_value
        update_all_positions_market_value(clean_prices)
    except Exception as ex:
        logger.warning(f"更新模拟账户市值异常: {ex}")
    
    logger.info(f"检查完成: 检查了 {checked_count} 个阈值, 跳过已推送 {skipped_already} 个, 本次触发 {len(triggered_msgs)} 个")

    # 输出（stdout 供调试/cron 可读，企微推送走 webhook）
    if triggered_msgs:
        # 拼接完整消息
        full_msg = f"🔔 盘中提醒 ({now.strftime('%H:%M')})\n" + ("=" * 40) + "\n"
        for m in triggered_msgs:
            full_msg += m + "\n" + ("-" * 40) + "\n"
        # 1) stdout (保留调试输出)
        print(full_msg)
        # 2) webhook 推送到企微群机器人
        if WEBHOOK_URL:
            ok = push_webhook(full_msg)
            logger.info(f"webhook 推送 {'成功' if ok else '失败'} | {len(triggered_msgs)} 条警报")
        else:
            logger.warning("未配置 webhook URL，跳过推送")
        logger.info(f"推送 {len(triggered_msgs)} 条警报给用户")
    else:
        # 没触发就只输出一行简短状态（cron 默认不通知）
        snapshot_str = " / ".join(f"{c}:{clean_prices.get(c, 0):.2f}" for c in codes if clean_prices.get(c))
        print(f"✓ {now.strftime('%H:%M')} 无新警报 | {snapshot_str}")
        logger.info(f"无新警报，静默返回")
    
    logger.info(f"==== 运行结束 run_id={run_id} ====\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
