"""
scripts/monitor_600330_sell.py — 天通股份 600330 智能定时卖出告警

功能：
  - 每 30 秒拉取一次实时行情
  - 根据时间档 + 价格条件，动态推送企微告警，提示用户去 QMT 操作
  - 同一档位同一日只推 1 次（防止刷屏）
  - 自动 14:58 退出（避免延迟到收盘后还在跑）

用法：
  python scripts/monitor_600330_sell.py
"""
import sys
import time
import json
import logging
import requests
from datetime import datetime, time as dtime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.config import load_config

CODE = '600330'
NAME = '天通股份'
QTY_REMAINING = 200  # 当前还剩 200 股待卖
COST = 32.818  # 成本价
STATE_FILE = ROOT / 'output' / 'monitor_600330_state.json'
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger('monitor-600330')
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')


def fetch_quote() -> dict | None:
    """从新浪拉实时行情"""
    try:
        r = requests.get(f'https://hq.sinajs.cn/list=sh{CODE}',
                         headers={'Referer': 'https://finance.sina.com.cn'},
                         timeout=5)
        data = r.text.split('=')[1].strip(';\n').strip('"').split(',')
        return {
            'name': data[0],
            'pre': float(data[2]),
            'cur': float(data[3]),
            'hi': float(data[4]),
            'lo': float(data[5]),
            'time': f'{data[30]} {data[31]}',
        }
    except Exception as e:
        logger.warning(f'行情拉取失败: {e}')
        return None


def push_wecom(content: str) -> bool:
    """推送企微"""
    cfg = load_config()
    webhook = (cfg.get('notifier') or {}).get('wecom_webhook', '')
    if not webhook:
        logger.warning('未配置 wecom_webhook，跳过推送')
        logger.info(f'[告警内容] {content}')
        return False
    try:
        resp = requests.post(webhook, json={
            'msgtype': 'markdown',
            'markdown': {'content': content}
        }, timeout=5)
        ok = resp.json().get('errcode') == 0
        logger.info(f'推送 {"成功" if ok else "失败"}: {resp.text[:80]}')
        return ok
    except Exception as e:
        logger.warning(f'推送异常: {e}')
        return False


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    return {}


def save_state(s: dict):
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2),
                          encoding='utf-8')


def in_window(now: datetime, start: str, end: str) -> bool:
    h1, m1 = map(int, start.split(':'))
    h2, m2 = map(int, end.split(':'))
    cur = now.time()
    return dtime(h1, m1) <= cur < dtime(h2, m2)


# ============================================================
# 决策表（按优先级，从上到下）
# ============================================================
RULES = [
    # 紧急止损：任何时段如果跌破 28.80（冲高失败）
    {
        'id': 'emergency_stop',
        'window': ('13:00', '14:58'),
        'cond': lambda q: q['cur'] < 28.80,
        'msg': lambda q: (
            f"## 🚨 天通冲高失败！\n"
            f"现价 **¥{q['cur']:.2f}** 已跌破 28.80 警戒线（最高 {q['hi']:.2f}）\n"
            f"**立刻去 QMT 全部市价清仓 {QTY_REMAINING} 股**\n"
            f"预计到手: {q['cur'] * QTY_REMAINING * 0.999:.0f} 元"
        ),
    },
    # 涨停区：≥30.00 抢挂高价
    {
        'id': 'near_limit_up',
        'window': ('13:00', '14:55'),
        'cond': lambda q: q['cur'] >= 30.00,
        'msg': lambda q: (
            f"## 🚀 天通接近涨停！\n"
            f"现价 **¥{q['cur']:.2f}** (+{(q['cur']/q['pre']-1)*100:.2f}%)\n"
            f"涨停价 30.25\n\n"
            f"**操作建议：**\n"
            f"- 第一手 100 股挂 30.20\n"
            f"- 第二手 100 股挂 30.25 (赌涨停封板)\n"
            f"- 14:30 还没成交改 29.80 / 14:50 改市价"
        ),
    },
    # 高位区：≥29.50 第一手出
    {
        'id': 'high_zone_first_lot',
        'window': ('13:00', '14:30'),
        'cond': lambda q: q['cur'] >= 29.50,
        'msg': lambda q: (
            f"## ⚡ 天通拉至 ¥{q['cur']:.2f}\n"
            f"涨幅 +{(q['cur']/q['pre']-1)*100:.2f}%\n\n"
            f"**操作：先卖第一手 100 股 @市价**（避免冲高回落）\n"
            f"剩 100 股留给冲涨停\n"
            f"预计第一手到手: {q['cur'] * 100 * 0.999:.0f} 元"
        ),
    },
    # 14:30-14:45 中场降档
    {
        'id': 'mid_30_45',
        'window': ('14:30', '14:45'),
        'cond': lambda q: q['cur'] >= 29.30,
        'msg': lambda q: (
            f"## 💰 14:30 时点回顾\n"
            f"现价 **¥{q['cur']:.2f}** (+{(q['cur']/q['pre']-1)*100:.2f}%)\n\n"
            f"**操作：第一手 100 股挂卖 ¥{q['cur']:.2f} 保平**\n"
            f"剩 100 股观察至 14:45"
        ),
    },
    # 14:45-14:55 尾盘抢卖
    {
        'id': 'tail_45_55_high',
        'window': ('14:45', '14:55'),
        'cond': lambda q: q['cur'] >= 29.00,
        'msg': lambda q: (
            f"## ⏰ 尾盘 14:45 决策时点\n"
            f"现价 **¥{q['cur']:.2f}**（剩 15 分钟）\n\n"
            f"**操作：剩余 {QTY_REMAINING} 股全部市价！**\n"
            f"不要再赌涨停，避免参与集合竞价亏价\n"
            f"预计到手: {q['cur'] * QTY_REMAINING * 0.999:.0f} 元"
        ),
    },
    {
        'id': 'tail_45_55_low',
        'window': ('14:45', '14:55'),
        'cond': lambda q: q['cur'] < 29.00,
        'msg': lambda q: (
            f"## ⏰ 尾盘 14:45 — 没冲上去！\n"
            f"现价 **¥{q['cur']:.2f}** (从最高 {q['hi']:.2f} 回落)\n\n"
            f"**操作：剩余 {QTY_REMAINING} 股立刻市价！**\n"
            f"预计到手: {q['cur'] * QTY_REMAINING * 0.999:.0f} 元"
        ),
    },
    # 最后 5 分钟兜底
    {
        'id': 'final_5min',
        'window': ('14:55', '14:58'),
        'cond': lambda q: True,
        'msg': lambda q: (
            f"## ⛔ 最后 5 分钟！\n"
            f"现价 **¥{q['cur']:.2f}** (+{(q['cur']/q['pre']-1)*100:.2f}%)\n\n"
            f"**最后机会：剩余 {QTY_REMAINING} 股**\n"
            f"- 立刻市价单 @现价\n"
            f"- 或挂 14:57 集合竞价（高开/平开都接受）\n"
            f"切勿留隔夜跨周！"
        ),
    },
]


def main():
    logger.info(f'=== 天通 600330 卖出监控启动 (剩余 {QTY_REMAINING} 股, 成本 {COST}) ===')
    push_wecom(
        f"## ⚡ 天通智能卖出监控已启动\n"
        f"**剩余持仓**: {QTY_REMAINING} 股 @ 成本 ¥{COST}\n"
        f"**监控时段**: 即时 → 14:58\n"
        f"**触发档位**:\n"
        f"- ≥30.00: 抢挂涨停\n"
        f"- ≥29.50: 第一手卖出\n"
        f"- 14:45 后: 强制清仓\n"
        f"- <28.80: 紧急止损\n"
        f"- 14:55 后: 尾盘最终告警\n\n"
        f"📊 每 30 秒检查一次价格"
    )

    while True:
        now = datetime.now()
        # 自动退出时间
        if now.time() >= dtime(14, 58):
            push_wecom(f"## ✅ 监控结束（14:58）\n请检查 QMT 持仓是否清空")
            logger.info('14:58 到点，退出')
            break

        # 周末跳过
        if now.weekday() >= 5:
            logger.info('周末，退出')
            break

        # 午休时段跳过（11:30-13:00）
        if dtime(11, 30) <= now.time() < dtime(13, 0):
            logger.info('午休时段，等待...')
            time.sleep(60)
            continue

        # 早盘前等待
        if now.time() < dtime(9, 30):
            logger.info(f'未开盘，等待...')
            time.sleep(60)
            continue

        # 拉行情
        q = fetch_quote()
        if not q:
            time.sleep(30)
            continue

        logger.info(
            f"现价 {q['cur']:.2f} (+{(q['cur']/q['pre']-1)*100:.2f}%) "
            f"高 {q['hi']:.2f} 低 {q['lo']:.2f} @ {q['time'].split()[1]}"
        )

        state = load_state()
        today = now.strftime('%Y%m%d')
        fired_today = state.get(today, {})

        # 检查每条规则
        for rule in RULES:
            if fired_today.get(rule['id']):
                continue
            if not in_window(now, rule['window'][0], rule['window'][1]):
                continue
            if not rule['cond'](q):
                continue
            # 触发！
            msg = rule['msg'](q)
            push_wecom(msg)
            logger.info(f"🔔 触发 {rule['id']}: 现价 {q['cur']}")
            fired_today[rule['id']] = {
                'time': now.strftime('%H:%M:%S'),
                'price': q['cur'],
            }
            state[today] = fired_today
            save_state(state)

            # 紧急止损/最终兜底触发后直接退出
            if rule['id'] in ('emergency_stop', 'final_5min'):
                logger.info(f'{rule["id"]} 已触发，退出')
                return

            break  # 一次只触发最高优先级的一条

        time.sleep(30)


if __name__ == '__main__':
    main()
