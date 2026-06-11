"""
scripts/monitor_002453_monday.py — 华软科技 002453 周一开盘智能告警

策略：根据 9:25 集合竞价开盘价 + 9:30 后 5 分钟走势，分档推告警
持仓: 300 股 @ 成本 6.467
"""
import sys, time, requests, logging, json
from datetime import datetime, time as dtime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.config import load_config

CODE = '002453'
NAME = '华软科技'
QTY = 300
COST = 6.467

STATE_FILE = ROOT / 'output' / 'monitor_002453_state.json'
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger('mon-002453')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')


def fetch():
    try:
        r = requests.get(f'https://hq.sinajs.cn/list=sz{CODE}',
                         headers={'Referer': 'https://finance.sina.com.cn'}, timeout=5)
        d = r.text.split('=')[1].strip(';\n').strip('"').split(',')
        return {
            'name': d[0], 'pre': float(d[2]), 'cur': float(d[3]),
            'hi': float(d[4]), 'lo': float(d[5]), 'open': float(d[1]),
            'time': f'{d[30]} {d[31]}',
        }
    except Exception as e:
        logger.warning(f'拉取失败: {e}')
        return None


def push(content):
    cfg = load_config()
    webhook = (cfg.get('notifier') or {}).get('wecom_webhook', '')
    if not webhook:
        logger.info(f'[告警] {content}')
        return
    try:
        resp = requests.post(webhook, json={'msgtype': 'markdown', 'markdown': {'content': content}}, timeout=5)
        logger.info(f'推送: {resp.text[:60]}')
    except Exception as e:
        logger.warning(f'推送异常: {e}')


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    return {}


def save_state(s):
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    logger.info(f'=== 周一华软开盘监控 ({QTY}股 @{COST}) ===')
    push(
        f"## 📅 周一华软开盘监控启动\n"
        f"**持仓**: {QTY} 股 @ 成本 ¥{COST}\n"
        f"**昨日涨停收盘**: 6.26\n\n"
        f"**📊 决策表（开盘价 vs 昨收 6.26）：**\n"
        f"- 高开 +5% 以上 (≥6.57): 立刻挂 6.51 抢卖\n"
        f"- 高开 +2~5% (6.38~6.57): 9:30 开盘市价\n"
        f"- 平开 ±2% (6.13~6.38): 观察 5 分钟，放量上攻则等 +3% 卖、缩量阴跌则市价\n"
        f"- 低开 -2% 以下 (<6.13): 立刻市价\n\n"
        f"⏰ 9:25 集合竞价 / 9:30 开盘 / 9:35 五分钟决策"
    )

    state = load_state()
    today = datetime.now().strftime('%Y%m%d')
    fired = state.get(today, {})

    while True:
        now = datetime.now()
        if now.weekday() >= 5:
            logger.info('周末，退出')
            break
        if now.time() >= dtime(9, 45):
            logger.info('9:45 决策窗口已过，退出')
            push(f"## ✅ 华软周一监控结束（9:45）\n请检查 QMT 持仓状态")
            break
        if now.time() < dtime(9, 20):
            time.sleep(60)
            continue

        q = fetch()
        if not q:
            time.sleep(15)
            continue

        cur, pre = q['cur'], q['pre']
        chg = (cur / pre - 1) * 100 if pre else 0
        logger.info(f"现 {cur:.2f} ({chg:+.2f}%) 昨 {pre:.2f}")

        # ========== 9:25 集合竞价（开盘价已确定）==========
        if dtime(9, 25) <= now.time() < dtime(9, 30) and not fired.get('auction'):
            open_price = q.get('open') or cur
            open_chg = (open_price / pre - 1) * 100 if pre else 0
            if open_chg >= 5:
                push(
                    f"## 🚀 华软高开 +{open_chg:.2f}% ¥{open_price:.2f}\n"
                    f"**集合竞价立即挂 6.51（+4%）抢成交！**\n"
                    f"成本 6.467，6.51 = 平本！\n"
                    f"预计到手: {open_price * QTY * 0.999:.0f} 元"
                )
            elif open_chg >= 2:
                push(
                    f"## 📈 华软高开 +{open_chg:.2f}% ¥{open_price:.2f}\n"
                    f"**9:30 开盘后立即挂市价**\n"
                    f"距成本 6.467 还差 {((cur/COST)-1)*100:+.2f}%"
                )
            elif open_chg >= -2:
                push(
                    f"## 🟡 华软平开 {open_chg:+.2f}% ¥{open_price:.2f}\n"
                    f"**观察 5 分钟（9:35）再决策**\n"
                    f"- 放量上攻 → 挂 6.45 等成交\n"
                    f"- 缩量阴跌 → 市价立刻清"
                )
            else:
                push(
                    f"## 🚨 华软低开 {open_chg:.2f}% ¥{open_price:.2f}\n"
                    f"**冲高失败！9:30 开盘立刻市价清！**\n"
                    f"避免变成「涨停接力 → 二次套牢」\n"
                    f"预计到手: {open_price * QTY * 0.999:.0f} 元"
                )
            fired['auction'] = {'open': open_price, 'chg': open_chg}
            state[today] = fired
            save_state(state)

        # ========== 9:35 开盘 5 分钟决策 ==========
        if dtime(9, 35) <= now.time() < dtime(9, 36) and not fired.get('after_open_5min'):
            chg5 = (cur / pre - 1) * 100 if pre else 0
            high5_chg = (q['hi'] / pre - 1) * 100 if pre else 0
            push(
                f"## ⏰ 华软开盘 5 分钟回顾\n"
                f"- 现价 ¥{cur:.2f} ({chg5:+.2f}%)\n"
                f"- 9:30-9:35 最高 ¥{q['hi']:.2f} ({high5_chg:+.2f}%)\n"
                f"- 距成本 6.467 还差 {((cur/COST)-1)*100:+.2f}%\n\n"
                f"**操作建议**：\n"
                f"- 现价 ≥6.45: 挂 6.50 等成交（接近平本）\n"
                f"- 现价 6.20-6.45: 市价清（不要再贪）\n"
                f"- 现价 <6.20: 市价立刻清（趋势变弱）"
            )
            fired['after_open_5min'] = {'price': cur, 'chg': chg5}
            state[today] = fired
            save_state(state)

        time.sleep(15)


if __name__ == '__main__':
    main()
