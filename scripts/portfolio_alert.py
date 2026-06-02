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
import json, sys, logging, traceback, urllib.request, io, os
from datetime import datetime, time as dtime
from pathlib import Path

def configure_stdio() -> None:
    """强制 stdout/stderr 使用 UTF-8（避免 Windows 计划任务下 GBK 编码 emoji 崩溃）。

    只在脚本入口调用，避免模块导入时替换 pytest/调用方的捕获流。
    """
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
    """从 config.yaml 读 notify.wecom_webhook，读不到返回 None"""
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
        url = (cfg.get('notify') or {}).get('wecom_webhook', '') or ''
        if url:
            return url
    except Exception:
        pass
    # 兼容旧路径：config.local.yaml
    try:
        import yaml
        local_cfg = ROOT / 'config.local.yaml'
        if local_cfg.exists():
            data = yaml.safe_load(local_cfg.read_text(encoding='utf-8')) or {}
            return (data.get('notifier') or {}).get('wecom_webhook', '') or ''
    except Exception:
        pass
    return None

WEBHOOK_URL = None  # 延迟到交易时段内加载，避免非交易时段空跑读取配置

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
logger = logging.getLogger("portfolio_alert")
logger.addHandler(logging.NullHandler())


def setup_logging() -> None:
    """按需启用日志。

    BUG-015: portfolio_alert 可能被 Windows 计划任务全天每 10 分钟唤起。
    非交易时段应尽早静默退出，不能仅为了打印“非交易时段”而持续写
    output/runner.log / output/portfolio_alert.log。因此日志只在确认进入
    交易时段后配置。
    """
    if getattr(setup_logging, "_configured", False):
        return

    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stderr)  # 控制台 stderr不干扰 stdout 传递给 cron
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    logger.propagate = False
    setup_logging._configured = True

# ====================================================================
#  阈值规则表（行动手册）
# ====================================================================
#  阈值规则表（2026-05-22 重构：从 config.yaml + sim_live_mirror.db 加载）
#  + 2026-05-25 支持分层观察列表（user_manual / auto_discovered）
#
#  以前这里是硬编码 RULES 列表，现在由 sim/portfolio.py 统一供应：
#    - 持仓股规则 ← config.yaml: real_portfolio_rules
#    - 观察股规则 ← config.yaml: watchlist (user_manual + auto_discovered)
#    - 持仓数量/成本 ← sim_live_mirror.db (account_id=2 真实账户)
#
#  修改规则请改 config.yaml 。
# ====================================================================
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from sim.portfolio import load_all_alert_rules  # noqa: E402
RULES = None  # 延迟到交易时段内加载，避免非交易时段 cron 空跑消耗资源


# ====================================================================
#  交易计划计算（买入信号附带盈亏比）
# ====================================================================
TOTAL_CAPITAL = 100000  # 学习账户总资金
MAX_SINGLE_PCT = 0.10    # 单只最多 10%
LOT_SIZE = 100           # A股最小单位


def calc_trade_plan(code: str, entry_price: float, triggered_rule: dict, all_rules: list) -> str:
    """
    计算交易计划：止损/止盈/盈亏比/仓位建议

    止损 = 同一股票的 trend_break 触发价（如果没有，用 entry_price × 0.92）
    止盈① = entry_price × 1.15（+15%）
    止盈② = entry_price × 1.25（+25%）
    盈亏比 = (止盈① - entry_price) / (entry_price - 止损)
    仓位 = 总资金的 5%（即约 ¥5,000 / entry_price 取整到 100 股）
    """
    # 找同一股票的 trend_break 规则
    trend_break_price = None
    for r in all_rules:
        if r['code'] == code and 'trend_break' in r['level']:
            trend_break_price = r['trigger']
            break
    
    # 止损取 trend_break 和 -8% 中较近的那个（较大值 = 较小亏损）
    default_stop = round(entry_price * 0.92, 2)
    if trend_break_price and trend_break_price > 0:
        stop_loss = max(trend_break_price, default_stop)
    else:
        stop_loss = default_stop
    
    stop_reason = "跌破 trend_break" if (trend_break_price and stop_loss == trend_break_price) else "-8%止损"
    
    # 止盈
    take_profit_1 = round(entry_price * 1.15, 2)
    take_profit_2 = round(entry_price * 1.25, 2)
    
    # 盈亏比
    risk = entry_price - stop_loss
    if risk <= 0:
        return ""  # 止损高于买入价，计算无意义
    reward = take_profit_1 - entry_price
    rr_ratio = round(reward / risk, 2)
    
    # 盈亏比标签
    if rr_ratio >= 2.0:
        rr_label = f"{rr_ratio}:1 ✅ 优秀"
    elif rr_ratio >= 1.5:
        rr_label = f"{rr_ratio}:1 ✅ 可行"
    else:
        rr_label = f"{rr_ratio}:1 ⚠️ 盈亏比偏低，建议观望"
    
    # 仓位建议（总资金 5%）
    budget = TOTAL_CAPITAL * 0.05
    # 不超过单只上限
    max_budget = TOTAL_CAPITAL * MAX_SINGLE_PCT
    budget = min(budget, max_budget)
    shares = int(budget / entry_price / LOT_SIZE) * LOT_SIZE
    if shares < LOT_SIZE:
        shares = LOT_SIZE
    cost = round(shares * entry_price, 0)
    
    # 止损百分比
    stop_pct = round((stop_loss - entry_price) / entry_price * 100, 1)
    
    plan = (
        f"\n📐 交易计划（盈亏比 {rr_ratio}:1）\n"
        f"├ 建议买入：¥{entry_price:.2f}\n"
        f"├ 止损：¥{stop_loss:.2f}（{stop_pct}%，{stop_reason}）\n"
        f"├ 止盈①：¥{take_profit_1:.2f}（+15%）\n"
        f"├ 止盈②：¥{take_profit_2:.2f}（+25%）\n"
        f"├ 盈亏比：{rr_label}\n"
    )
    
    # 概率估算（基于历史数据）
    try:
        from calc_probability import calc_expected_trade
        prob = calc_expected_trade(code, entry_price, tp_pct=0.15, sl_pct=abs(stop_pct)/100, hold_days=10)
        if prob:
            plan += (
                f"├ 止盈概率：{prob['p_tp']*100:.0f}% | 止损概率：{prob['p_sl']*100:.0f}%\n"
                f"├ 期望收益：{prob['expected_pct']:+.2f}%"
            )
            if prob['expected_pct'] >= 3:
                plan += " ⭐ 优秀"
            elif prob['expected_pct'] >= 1.5:
                plan += " ✅ 可行"
            elif prob['expected_pct'] >= 0:
                plan += " ❓ 一般"
            else:
                plan += " ⚠️ 负期望，建议观望"
            plan += "\n"
            if prob['kelly_pct'] > 0:
                kelly_amt = int(TOTAL_CAPITAL * prob['kelly_pct'] / (entry_price * LOT_SIZE)) * LOT_SIZE * entry_price
                plan += f"├ Kelly仓位：{prob['kelly_pct']*100:.1f}%（≈¥{kelly_amt:,.0f}）\n"
    except Exception:
        pass  # 概率计算失败不影响主流程
    
    plan += f"└ 仓位建议：{shares} 股 ≈ ¥{cost:,.0f}"
    return plan


def get_rr_ratio_for_rule(code: str, entry_price: float, all_rules: list) -> float:
    """快速计算盈亏比，用于决定消息前缀。P1: 优先 ATR 止损。"""
    stop_loss = None
    # P1: 优先从 trend_filter.atr_stop_pct 取动态止损
    for r in all_rules:
        if r['code'] == code:
            tf = r.get('trend_filter') or {}
            if tf.get('atr_stop_pct'):
                stop_loss = round(entry_price * (1 - float(tf['atr_stop_pct']) / 100), 2)
                break
    if stop_loss is None:
        for r in all_rules:
            if r['code'] == code and 'trend_break' in r['level']:
                stop_loss = r['trigger']
                break
    if stop_loss is None or stop_loss <= 0:
        stop_loss = entry_price * 0.92
    
    risk = entry_price - stop_loss
    if risk <= 0:
        return 0.0
    reward = entry_price * 0.15  # +15% 止盈
    return reward / risk


def get_now() -> datetime:
    """返回当前时间；测试可用 PORTFOLIO_ALERT_NOW 注入固定时间。"""
    override = os.environ.get("PORTFOLIO_ALERT_NOW")
    if override:
        return datetime.fromisoformat(override)
    return datetime.now()


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



def _learn_position_qty(code: str) -> int:
    """Return current learn-account holding quantity for a stock."""
    try:
        from sim.portfolio import fetch_positions, learn_account_id
        for pos in fetch_positions(learn_account_id()):
            if str(pos.get('stock_code')) == str(code):
                return int(pos.get('quantity') or 0)
    except Exception as e:
        logger.warning(f"查询学习账户持仓失败 {code}: {e}")
    return 0
def is_triggered(price: float, trigger: float, direction: str) -> bool:
    if direction == "below":
        return price <= trigger
    else:  # above
        return price >= trigger


def main():
    now = get_now()

    if not in_trade_hours(now):
        # BUG-015: 非交易时段会被计划任务频繁唤起；必须早起检跳且完全静默，
        # 避免 output/runner.log 与 output/portfolio_alert.log 全天膨胀。
        return 0

    setup_logging()
    global RULES, WEBHOOK_URL
    if RULES is None:
        RULES = load_all_alert_rules()
    if WEBHOOK_URL is None:
        WEBHOOK_URL = _load_webhook()

    today = now.strftime("%Y-%m-%d")
    run_id = now.strftime("%H%M%S")
    
    logger.info(f"==== 运行开始 run_id={run_id} ====")

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
    
    # P2: 为所有学习账户持仓更新跟踪止损（钉住高点、抬高止损位）
    try:
        from sim_executor import update_position_trailing
        import sqlite3
        sim_db = ROOT / 'data' / 'sim_live_mirror.db'
        if sim_db.exists():
            conn = sqlite3.connect(sim_db)
            held_codes = [(row[0], row[1]) for row in conn.execute(
                "SELECT account_id, stock_code FROM sim_positions WHERE quantity > 0"
            ).fetchall()]
            conn.close()
            trailing_updates = 0
            for acc_id, code in held_codes:
                cur_p = clean_prices.get(code, 0)
                if cur_p > 0:
                    res = update_position_trailing(acc_id, code, cur_p)
                    if res.get('updated') and res.get('trailing'):
                        trailing_updates += 1
            logger.info(f"P2 跟踪止损更新了 {trailing_updates}/{len(held_codes)} 个仓位")
    except Exception as e:
        logger.warning(f"P2 跟踪止损更新异常: {e}")

    triggered_msgs = []
    checked_count = 0
    skipped_already = 0
    
    # REQ-046: 自动检查严重浮亏个股并触发止损
    try:
        import sqlite3
        from pathlib import Path
        DB_PATH = Path(__file__).resolve().parents[1] / 'data' / 'sim_live_mirror.db'
        
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        positions = conn.execute(
            "SELECT account_id, stock_code, stock_name, quantity, avg_cost, current_price, pnl_pct, "
            "trailing_stop_price "
            "FROM sim_positions WHERE quantity > 0"
        ).fetchall()
        conn.close()
        
        for pos in positions:
            pnl_pct = pos['pnl_pct'] or 0
            cur_price = float(pos['current_price'] or 0)
            fallback_stop = float(pos['avg_cost'] or 0) * 0.92
            trailing_stop = float(pos['trailing_stop_price'] or 0)
            effective_stop = max(fallback_stop, trailing_stop)
            stop_source = '跟踪止损' if trailing_stop > fallback_stop else '-8%原始止损'
            # REQ-041: 优先使用 trailing_stop_price；没有启动时才回退到原始 -8%。
            if effective_stop > 0 and cur_price > 0 and cur_price <= effective_stop and pos['quantity'] > 0:
                logger.warning(
                    f"🚨 自动止损触发: {pos['stock_code']} 现价 {cur_price:.2f} <= "
                    f"{stop_source} {effective_stop:.2f} (浮盈亏 {pnl_pct:.2f}%)"
                )
                
                # 构造止损 rule
                rule = {
                    'code': pos['stock_code'],
                    'name': pos['stock_name'],
                    'level': 'stop_loss',
                    'trigger': effective_stop,
                    'dir': 'below',
                    'message': f'自动止损 ({stop_source} ¥{effective_stop:.2f}, 浮盈亏 {pnl_pct:.2f}%)',
                    'source': 'auto'
                }
                
                # 执行虚拟卖出；只有真正记录了模拟卖单才推用户。
                # 软止损/无持仓等结果只记日志，避免误导成“已下单”。
                from sim_executor import execute_trade
                result = execute_trade(rule, cur_price)
                message = str(result.get('message', ''))

                if result.get('success') and '卖出' in message:
                    logger.info(f"✅ 已记录模拟止损卖单: {message}")
                    triggered_msgs.append(
                        f"🚨 模拟止损卖单: {pos['stock_code']} 现价¥{cur_price:.2f} 触发{stop_source}¥{effective_stop:.2f} → {message}"
                    )
                elif result.get('success'):
                    logger.info(f"ℹ️ 止损提醒已评估: {message}")
                else:
                    logger.warning(f"⚠️ 止损提醒未下单: {message}")
    except Exception as e:
        logger.warning(f"自动止损检查异常: {e}")
    
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
            # Sell-side rules are meaningful only when the learn account still has a position.
            # If the simulated position has already been sold, skip both the user alert and
            # the virtual order attempt.
            sell_levels = {'take_profit', 'take_profit_half', 'trend_break', 'trend_break_warn', 'stop_loss', 'stop_loss_tight', 'hard_stop', 'trailing_stop'}
            if rule['source'] == 'real' and rule['level'] in sell_levels:
                qty = _learn_position_qty(code)
                if qty <= 0:
                    logger.info(f"跳过卖出提醒: {code} 无学习账户持仓 level={rule['level']}")
                    today_state[rule_id] = {
                        'triggered_at': now.strftime('%H:%M'),
                        'price': cur_price,
                        'trigger': rule['trigger'],
                        'skipped': 'no_learn_position',
                    }
                    skipped_already += 1
                    continue
            arrow = "↓" if rule["dir"] == "below" else "↑"
            msg = (f"【{rule['name']} {code}】\n"
                   f"现价 ¥{cur_price:.2f} {arrow} 阈值 ¥{rule['trigger']:.2f}\n"
                   f"{rule['message']}")
            
            # 买入信号附带交易计划 + 盈亏比
            if 'buy' in rule['level']:
                all_rules_for_code = [r for r in RULES if r['code'] == code]
                plan = calc_trade_plan(code, cur_price, rule, all_rules_for_code)
                if plan:
                    # 检查盈亏比，决定前缀
                    rr = get_rr_ratio_for_rule(code, cur_price, all_rules_for_code)
                    if rr < 1.5 and rr > 0:
                        # 替换消息开头的 💰 为 ⚠️💰
                        msg = msg.replace("💰💰", "⚠️💰💰", 1) if "💰💰" in msg else msg.replace("💰", "⚠️💰", 1)
                    msg += plan
            
            # REQ-018: 单票止损止盈预警和建议
            if rule['source'] == 'real' and rule['level'] in ('stop_loss', 'stop_loss_tight', 'hard_stop'):
                # 检查持仓亏损情况
                try:
                    from sim.portfolio import load_real_holdings
                    holdings = load_real_holdings()
                    for h in holdings:
                        if h['code'] == code:
                            if h['pnl_pct'] <= -0.15:
                                msg += f"\n🚨 警告：该票当前已浮亏 {h['pnl_pct']*100:.1f}%，超过15%红线！建议立即执行纪律平仓！"
                            elif h['pnl_pct'] <= -0.08:
                                msg += f"\n⚠️ 提示：该票当前浮亏 {h['pnl_pct']*100:.1f}%，已达8%止损区，请酌情减仓或平仓！"
                            break
                except Exception as ex:
                    logger.warning(f"附加止损提示异常: {ex}")

            elif rule['source'] == 'real' and rule['level'] in ('take_profit', 'take_profit_half', 'half_out'):
                try:
                    from sim.portfolio import load_real_holdings
                    holdings = load_real_holdings()
                    for h in holdings:
                        if h['code'] == code:
                            if h['pnl_pct'] >= 0.20:
                                msg += f"\n🎉 恭喜：该票当前已浮盈 {h['pnl_pct']*100:.1f}%，建议分批止盈锁定利润！"
                            elif h['pnl_pct'] >= 0.10:
                                msg += f"\n📈 提示：该票当前浮盈 {h['pnl_pct']*100:.1f}%，可考虑卖出半仓落袋为安。"
                            break
                except Exception as ex:
                    logger.warning(f"附加止盈提示异常: {ex}")
            
            # 虚拟下单（全自动模式 A）
            try:
                from sim_executor import execute_trade
                trade_result = execute_trade(rule, cur_price)
                # P0: 智能止损三档评级 — 把 severity 上下文带进消息
                sev = trade_result.get('severity')
                sev_label = trade_result.get('severity_label') or ''
                if sev_label:
                    msg += f"\n{sev_label}"
                if trade_result['success'] and trade_result['action'] != 'NO_ACTION':
                    msg += f"\n✅ 已记录模拟交易: {trade_result['message']}"
                    logger.warning(f"✅ 已记录模拟交易: {rule_id} → {trade_result['message']}")
                elif trade_result['success'] and trade_result['action'] == 'NO_ACTION' and sev == 'soft':
                    # 软止损（盘中）— 不下单只预警
                    msg += f"\n⏸️ 软止损：盘中暂不卖，等尾盘再判断（{trade_result['message']}）"
                    logger.warning(f"⚠️ 软止损推迟: {rule_id} → {trade_result['message']}")
                elif not trade_result['success']:
                    # 对卖出类提醒：下单失败通常说明已无模拟持仓，别再把“建议卖/失败”推给用户。
                    sell_levels = {'take_profit', 'take_profit_half', 'trend_break', 'trend_break_warn', 'stop_loss', 'stop_loss_tight', 'hard_stop', 'trailing_stop'}
                    if rule['source'] == 'real' and rule['level'] in sell_levels:
                        logger.warning(f"跳过卖出建议推送: {code} 模拟交易失败: {trade_result['message']}")
                        today_state[rule_id] = {
                            'triggered_at': now.strftime('%H:%M'),
                            'price': cur_price,
                            'trigger': rule['trigger'],
                            'skipped': 'virtual_sell_failed',
                            'message': trade_result['message'],
                        }
                        skipped_already += 1
                        continue
                    msg += f"\n⚠️ 模拟交易失败: {trade_result['message']}"
            except Exception as ex:
                logger.warning(f"虚拟下单异常: {ex}")
            
            triggered_msgs.append(msg)
            today_state[rule_id] = {
                "triggered_at": now.strftime("%H:%M"),
                "price": cur_price,
                "trigger": rule["trigger"],
            }
            logger.warning(f"🔔 触发阈值: {rule_id} 价={cur_price} 阈值={rule['trigger']} {rule['dir']}")
            
            # 更新 watchlist_history 的 last_alert_at（仅 watchlist 股票）
            if rule.get('source') == 'watchlist':
                try:
                    from sim.portfolio import update_watchlist_alert
                    # 判断 category（需要从 config.yaml 读取）
                    category = 'auto_discovered'  # 默认，实际应该查询 config
                    update_watchlist_alert(code, category)
                    logger.info(f"  ✓ 更新 watchlist_history: {code} last_alert_at={date.today()}")
                except Exception as ex:
                    logger.warning(f"更新 watchlist_history 失败: {ex}")

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
        full_msg = f"🔔 盘中提醒 {now.strftime('%Y-%m-%d %H:%M')}\n" + ("=" * 40) + "\n"
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
    configure_stdio()
    sys.exit(main())

